import re
f = open('credentials/test_clearances.py').read()
f = f.replace('b"1", content_type="image/jpeg"', 'b"%PDF-1.4\\n", content_type="application/pdf"')
f = f.replace('b"2", content_type="image/jpeg"', 'b"%PDF-1.4\\n", content_type="application/pdf"')
f = f.replace('.jpg"', '.pdf"')
open('credentials/test_clearances.py', 'w').write(f)

for path in ['credentials/permissions.py', 'credentials/serializers.py', 'credentials/views.py', 'credentials/test_clearances.py']:
    lines = [line.rstrip() for line in open(path).read().splitlines()]
    open(path, 'w').write('\n'.join(lines) + '\n')
