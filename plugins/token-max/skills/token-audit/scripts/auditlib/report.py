"""Small, reviewable evidence summary; full inventory stays in JSON."""


def cell(value):
    if value is None:
        return '—'
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('`', "'")


def table(rows, columns):
    if not rows:
        return ['None observed.']
    keys = list(columns)
    result = ['| ' + ' | '.join(columns.values()) + ' |',
              '| ' + ' | '.join('---' for _ in keys) + ' |']
    for row in rows:
        result.append('| ' + ' | '.join(cell(row.get(key, '—')) for key in keys) + ' |')
    return result


def render_full(report):
    project, session = report['project'], report['session']
    lines = ['# Token audit evidence', '', f"Generated: {report['generated_at']}", '',
             f"Project: `{cell(project['root'])}`", '',
             f"Text tokenizer: **{report['text_encoding'] or 'none; bytes/lines only'}**. "
             'Text tokens exclude framing and are not billed usage.', '',
             '## Recorded usage', '']
    if session:
        lines.extend([f"Log: `{cell(session['path'])}`", '',
                      f"Latest cumulative snapshot: line {session['usage_line']} ({session['usage_source']}).", ''])
        if session['usage'] is not None:
            lines.extend(table([{'metric': key, 'count': val} for key, val in session['usage'].items()],
                               {'metric': 'Metric', 'count': 'Recorded tokens'}))
        else:
            lines.append('Unknown: no valid usage counters.')
        lines.extend(['', 'Cached input is a subset of input; reasoning is a subset of output. '
                      'Do not add them again. Do not sum cumulative snapshots.', '',
                      f"Models observed: {', '.join(map(cell, session['models'])) or 'unknown'}. "
                      f"Compaction events: {session['compactions']}.", '',
                      '## Largest logged tool outputs', ''])
        lines.extend(table(session['tool_outputs'][:10],
                     {'line': 'Log line', 'tool': 'Tool', 'bytes': 'Bytes',
                      'text_tokens': 'Text tokens', 'identical_output_count': 'Identical outputs'}))
        lines.extend(['', '## Repeated call candidates', ''])
        lines.extend(table(session['repeated_calls'], {'tool': 'Tool', 'count': 'Calls', 'lines': 'Log lines'}))
        lines.extend(['', '## Largest logged messages', ''])
        lines.extend(table(session['largest_messages'][:5],
                     {'line': 'Log line', 'role': 'Role', 'bytes': 'Bytes', 'text_tokens': 'Text tokens'}))
        lines.extend(['', '## Diagnostic candidates (independent of size)', ''])
        lines.extend(table(session['diagnostics'][:10],
                     {'line': 'Log line', 'tool': 'Tool', 'signals': 'Signals', 'exit_codes': 'Exit codes'}))
        lines.append(f"{session['diagnostic_count']} diagnostic candidates total; all references in JSON. "
                     'Heuristics can miss failures and flag benign text; absence is not success.')
    else:
        lines.append('Unknown: no session matching this project was found. Supply --session explicitly.')
    lines.extend(['', '## Instruction candidates', ''])
    lines.extend(table(project['instructions'][:15], {'path': 'Path', 'lines': 'Lines', 'bytes': 'Bytes',
                 'text_tokens': 'Text tokens', 'routing_lines': 'Routing review lines'}))
    lines.extend(['', '## Largest project files', ''])
    lines.extend(table(project['files'][:10], {'path': 'Path', 'lines': 'Lines', 'bytes': 'Bytes',
                                            'text_tokens': 'Text tokens'}))
    lines.extend(['', '## Largest Python functions', ''])
    lines.extend(table(project['functions'][:10], {'path': 'Path', 'name': 'Function', 'line': 'Start', 'lines': 'Lines'}))
    lines.extend(['', '## Coverage and limits', '',
                 f"Scanned {project['files_scanned']} files via {project['inventory_method']}; "
                 f"exclusions: {project['excluded_counts']}.", ''])
    notes = project['warnings'] + project['limits']
    if session:
        notes += session['warnings'] + session['limits']
    lines.extend('- ' + note for note in notes)
    lines.extend(['', '## Next: evidence-backed review', '',
                  'Inspect only the leading candidates. For each recommendation cite a file or log line, '
                  'explain the mechanism, mark measured/estimated/hypothesis, and specify a quality-preserving '
                  'validation. Actual savings remain unmeasured until comparable before/after runs exist.', ''])
    return '\n'.join(lines)


def render(report):
    if report.get('full_report'):
        return render_full(report)
    project, session = report['project'], report['session']
    lines = ['# Token audit: report only', '']
    if session:
        lines.append(f"Log: `{cell(session['path'])}`; usage line {session['usage_line']}.")
        value = session['usage']
        if value:
            lines.append(f"Recorded input {value['input_tokens']}; cached subset {value['cached_input_tokens']}; "
                         f"output {value['output_tokens']}; reasoning subset {value['reasoning_output_tokens']}; "
                         f"total {value['total_tokens']}.")
        else:
            lines.append('Recorded usage unknown.')
        if session['diagnostics']:
            lines.append(f"\nDiagnostics: {session['diagnostic_count']} candidates; inspect before removing work.")
            for row in session['diagnostics'][:3]:
                lines.append(f"- Log {row['line']}: {', '.join(row['signals'])}; exits {row['exit_codes']}.")
            if session['diagnostic_count'] > 3:
                lines.append('Additional diagnostic references in evidence.json; none discarded there.')
        else:
            lines.append('No failure markers detected; this does not establish success.')
        for row in session['repeated_calls'][:3]:
            lines.append(f"- Review repeated {cell(row['tool'])}: {row['count']} calls, lines {row['lines']}.")
        for row in session['tool_outputs'][:3]:
            lines.append(f"- Inspect output at log {row['line']}: {row['bytes']} bytes; "
                         f"text tokens {cell(row['text_tokens'])}.")
    else:
        lines.append('No matching session; recorded usage unknown.')
    lines.append(f"\nProject: {project['files_scanned']} files scanned. Largest context candidates:")
    for row in project['instructions'][:2]:
        lines.append(f"- Instruction `{cell(row['path'])}`: {row['bytes']} bytes; activation unverified.")
    for row in project['files'][:2]:
        lines.append(f"- File `{cell(row['path'])}`: {row['bytes']} bytes; relevance must be checked.")
    warnings = project['warnings'] + (session['warnings'] if session else [])
    for warning in warnings[:3]:
        lines.append('- ' + cell(warning))
    if len(warnings) > 3:
        lines.append(f'{len(warnings) - 3} more warnings in evidence.json; review before conclusions.')
    lines.extend(['', f"Text encoding: {report['text_encoding'] or 'none; bytes only'}. "
                  'Sizes are not billed savings. Bodies omitted; retrieve relevant evidence locally. '
                  'Full inventory, diagnostics and limits: evidence.json. '
                  'Propose changes with evidence and acceptance checks; never apply them in this audit.', ''])
    return '\n'.join(lines)
