"""Text measurements are separate from provider usage counters."""
import hashlib


class TextMeter:
    def __init__(self, encoding=None):
        self.encoding = encoding
        self.tokenizer = None
        if encoding:
            try:
                import tiktoken
            except ImportError as exc:
                raise ValueError('Install optional tiktoken, or omit --encoding.') from exc
            self.tokenizer = tiktoken.get_encoding(encoding)

    def measure(self, text):
        return {
            'bytes': len(text.encode('utf-8')),
            'lines': len(text.splitlines()),
            'text_tokens': len(self.tokenizer.encode(text, disallowed_special=()))
            if self.tokenizer else None,
        }


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
