#!/usr/bin/env python3
"""Convert catalogue HTML to terminal text without altering shell examples."""
import re
import sys
from html.parser import HTMLParser


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif not self.hidden:
            if tag in ('p', 'div', 'br', 'ul', 'ol', 'pre', 'blockquote',
                       'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                self.parts.append('\n')
            elif tag == 'li':
                self.parts.append('\n• ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ('p', 'div', 'li', 'ul', 'ol', 'pre',
                                        'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    parser = PlainText()
    parser.feed(value)
    parser.close()
    result = ''.join(parser.parts).replace('\xa0', ' ')
    result = '\n'.join(line.strip() for line in result.splitlines())
    return re.sub(r'\n{3,}', '\n\n', result).strip()


if __name__ == '__main__':
    sys.stdout.write(plain_text(sys.stdin.read()))
