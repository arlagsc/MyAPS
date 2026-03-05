import requests
r = requests.get('http://localhost:5000/api/schedule_data')
data = r.json()

print('Sample scheduled tasks:')
for item in data['items'][:10]:
    print(f"{item['id']}: product={item.get('product', 'N/A')}, line={item['group']}")
