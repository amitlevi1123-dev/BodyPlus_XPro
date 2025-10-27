import requests

API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"
url = "https://api.runpod.ai/v2/pcw665a3g3k5pk/run"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

data = {
    "input": {
        "prompt": "hello from BodyPlus_XPro test"
    }
}

response = requests.post(url, headers=headers, json=data)

print("Status:", response.status_code)
print("Response:")
print(response.text)
