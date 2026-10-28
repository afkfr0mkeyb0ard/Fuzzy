## Fuzzy

```
usage: fuzzy.py [-h] -u URL -w WORDLIST [-X METHOD] [-t THREADS] [--delay DELAY] [-H HEADERS] [-d DATA]
               [-p PARAMS] [-mc MATCH_CODES] [-fc FILTER_CODES] [--proxy PROXY] [--progress] [--title] [-s]
               [-o OUTPUT]

Async Web Fuzzer — high concurrency

options:
  -h, --help            show this help message and exit
  -u, --url URL         Target URL (use FUZZ as placeholder)
  -w, --wordlist WORDLIST
                        Path to wordlist
  -X, --method METHOD   HTTP method
  -t, --threads THREADS
                        Number of concurrent workers
  --delay DELAY         Delay (seconds) between requests
  -H, --headers HEADERS
                        Custom headers: 'User-Agent=xyz'
  -d, --data DATA       POST data
  -p, --params PARAMS   Query parameters
  -mc, --match-codes MATCH_CODES
                        HTTP codes to match, e.g., 200,301
  -fc, --filter-codes FILTER_CODES
                        HTTP codes to filter
  --proxy PROXY         Proxy URL (http:// or socks5://)
  --progress            Show progress bar
  --title               Fetch page <title>
  -s, --silent          Silent output
  -o, --output OUTPUT   Output formats: txt,json,csv,html,xlsx

```

This repository is for **educational and research purposes only**. The author(s) and contributors are not responsible for any misuse, damage, or illegal activities caused by the information or code provided in this repository. By accessing or using this repository, you agree to use it responsibly and in compliance with all applicable local and international laws.
