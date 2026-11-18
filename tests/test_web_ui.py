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
    assert parser.modules==[] and parser.functions==[]
    assert 'weekly_plan/optimization.html' in html and 'daily_plan/inputs.html' in html and 'hourly_plan/control.html' in html
    assert '共享设备参数' in html and '共享电网模型' in html
    assert len(list(Path('web').glob('*_plan/*.html')))==12
    assert Path('web/shared/devices.html').exists() and Path('web/shared/network.html').exists()
    assert all('styles.css' in page.read_text(encoding='utf-8') for page in Path('web').glob('*_plan/*.html'))
    css=Path('web/styles.css').read_text(encoding='utf-8')
    assert 'overflow:hidden' in css
    assert 'overflow:auto' not in css
from fastapi.testclient import TestClient
from api.main import app

def test_each_function_is_a_real_html_page():
    client=TestClient(app)
    paths=['/','/weekly_plan/optimization.html','/weekly_plan/inputs.html','/weekly_plan/results.html','/weekly_plan/control.html','/daily_plan/optimization.html','/daily_plan/inputs.html','/daily_plan/results.html','/daily_plan/control.html','/hourly_plan/optimization.html','/hourly_plan/inputs.html','/hourly_plan/results.html','/hourly_plan/control.html','/shared/devices.html','/shared/network.html']
    for path in paths:
        response=client.get(path,follow_redirects=True)
        assert response.status_code==200,path
        assert '<html' in response.text and 'overflow:hidden' not in response.text
    assert client.get('/weekly_plan/unknown.html').status_code==404

def test_page_scoped_config_endpoints_are_independent():
    client=TestClient(app)
    old=client.get('/api/modules/hourly/optimization').json()
    updated={**old,'time_limit_seconds':11,'mip_gap':0.02}
    assert client.put('/api/modules/hourly/optimization',json=updated).status_code==200
    assert client.get('/api/modules/weekly/optimization').json()['time_limit_seconds'] != 11
    inputs=client.get('/api/modules/hourly/inputs').json()
    assert client.put('/api/modules/hourly/inputs',json=inputs).status_code==200
    assert client.get('/api/modules/hourly/inputs').json()['input_interval_minutes']==15
