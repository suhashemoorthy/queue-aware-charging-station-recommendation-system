import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URL = "http://127.0.0.1:8000/api/reservations"


def main():
    request = Request(URL, method="DELETE")
    try:
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"Could not clear reservations (HTTP {error.code}): {detail}")
        return 1
    except URLError as error:
        print(f"Could not reach the backend at {URL}: {error.reason}")
        print("Start the project with python3 executeev.py, then try again.")
        return 1

    print(f"Cleared {result['cleared']} reservation record(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())