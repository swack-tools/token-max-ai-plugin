#!/usr/bin/env python3
"""Check static HTML navigation, assets, domain, and the Pages publish boundary."""
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

SITE = Path(__file__).resolve().parents[1] / 'site'
ORIGIN = 'https://token-max.swacktech.com/'
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
ALLOWED = {'.html', '.css', '.js', '.svg', '.png', '.jpg', '.webp', '.ico', '.txt', '.xml'}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.stack, self.errors = set(), [], [], []
        self.canonical = None
        self.headings = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in VOID:
            self.stack.append(tag)
        if 'id' in attrs:
            if attrs['id'] in self.ids:
                self.errors.append(f'duplicate id: {attrs["id"]}')
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if key in attrs:
                self.links.append(attrs[key])
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'h1':
            self.headings += 1

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f'mismatched closing tag: {tag}')
        else:
            self.stack.pop()


def validate_site(site):
    site = site.resolve()
    errors, pages = [], {}
    try:
        if (site / 'CNAME').read_text().strip() != urlsplit(ORIGIN).hostname:
            errors.append('CNAME does not match the requested domain')
    except OSError:
        errors.append('CNAME is missing')
    for path in site.rglob('*'):
        if path.is_symlink():
            errors.append(f'symlink in publish directory: {path.name}')
        elif path.is_file():
            if path.name not in ('CNAME', '.nojekyll') and path.suffix not in ALLOWED:
                errors.append(f'unexpected publish file: {path.relative_to(site)}')
            if path.suffix == '.html':
                page = Page()
                page.feed(path.read_text())
                page.close()
                pages[path] = page
                errors.extend(f'{path.name}: {message}' for message in page.errors)
                if page.stack:
                    errors.append(f'{path.name}: unclosed tags: {page.stack}')
    home = pages.get(site / 'index.html')
    if not home or home.headings != 1 or home.canonical != ORIGIN:
        errors.append('index.html needs one h1 and the correct canonical URL')
    for path, page in pages.items():
        for link in page.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = ((site if parsed.path.startswith('/') else path.parent) / unquote(parsed.path).lstrip('/')).resolve() if parsed.path else path
            if target.is_dir():
                target = target / 'index.html'
            if not target.is_relative_to(site) or not target.is_file():
                errors.append(f'{path.name}: missing asset or page: {link}')
            elif parsed.fragment and target in pages and unquote(parsed.fragment) not in pages[target].ids:
                errors.append(f'{path.name}: missing anchor: {link}')
    return errors


if __name__ == '__main__':
    failures = validate_site(SITE)
    if failures:
        print('\n'.join(failures), file=sys.stderr)
        raise SystemExit(1)
    print('Site checks passed: HTML, navigation, assets, domain, and publish boundary.')
