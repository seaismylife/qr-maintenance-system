import urllib.request
import urllib.parse
import http.cookiejar
import re

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# 1. Fetch login page
resp = opener.open('http://127.0.0.1:5000/login')
html = resp.read().decode('utf-8')
token_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
token = token_match.group(1) if token_match else ''

# 2. Login as technician@school.edu
login_data = urllib.parse.urlencode({
    'email': 'technician@school.edu',
    'password': 'technician123',
    'csrf_token': token
}).encode('utf-8')

req = urllib.request.Request('http://127.0.0.1:5000/login', data=login_data)
login_resp = opener.open(req)

# 3. Access /maintenance_requests/
req_page = opener.open('http://127.0.0.1:5000/maintenance_requests/')
page_html = req_page.read().decode('utf-8')

print('--- Live Server Response for Technician User ---')
print('HTTP Status:', req_page.status)
print('Page Title contains My Assigned Tasks:', 'My Assigned Tasks' in page_html)
print('(You) badge removed (must be False):', '(You)' in page_html)
print('Submit button present:', 'Submit' in page_html)
print('Status select dropdown present:', '<select name="status"' in page_html)
print('Assigned to Tech 2 present (must be False):', 'Assigned to Tech 2' in page_html)
print('Tech 2 present in page (must be False):', 'Tech 2' in page_html)

rows = re.findall(r'<tr[^>]*>.*?</tr>', page_html, re.DOTALL)
print(f'Total table rows found: {len(rows)}')
for i, r in enumerate(rows):
    if '<th>' in r:
        continue
    eq = re.search(r'<strong>([^<]+)</strong>', r)
    eq_name = eq.group(1) if eq else 'Unknown'
    has_dropdown = '<select name="status"' in r
    has_submit = 'Submit' in r
    print(f'Row: {eq_name} | Dropdown: {has_dropdown} | Submit: {has_submit}')
