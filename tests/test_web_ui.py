from html.parser import HTMLParser
from pathlib import Path


def test_module_navigation_and_no_duplicate_ids():
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids, self.modules, self.functions = [], [], []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs: self.ids.append(attrs['id'])
            if 'data-module' in attrs: self.modules.append(attrs['data-module'])
            if 'data-function' in attrs: self.functions.append(attrs['data-function'])
    html = Path('web/index.html').read_text(encoding='utf-8')
    parser=Parser()
    parser.feed(html)
    assert len(parser.ids)==len(set(parser.ids))
    assert parser.modules==['weekly','daily','hourly']
    assert parser.functions==['optimization','inputs','results','control']
    assert '共享设备参数' in html and '共享电网模型' in html
    assert '柴油消耗量统计' in html
    assert '批量调整' in html and '能量与成本' in html and '比较当前/上一版' in html and 'data-page="stats:-1"' in html
    css=Path('web/styles.css').read_text(encoding='utf-8')
    assert 'overflow:hidden' in css
    assert 'overflow:auto' not in css
