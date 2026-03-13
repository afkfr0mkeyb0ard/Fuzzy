import asyncio
import httpx
import argparse
import re
import json
import signal
import sys
from time import time
from datetime import datetime
from tqdm import tqdm
from colorama import Fore, Style, init
import csv
from openpyxl import Workbook

init(autoreset=True)

# -------------------------------
# Globals
# -------------------------------
results = []
stop_flag = False
pause_flag = False
ctrl_c_count = 0
total_requests = 0
timeout_counter = 0
MAX_URL_LEN = 60

file_handles = {}
json_first = True
html_started = False
xlsx_wb = None
xlsx_ws = None

# -------------------------------
# Utils
# -------------------------------
def color_status(status):
    if 200 <= status < 300: return Fore.GREEN
    if 300 <= status < 400: return Fore.CYAN
    if 400 <= status < 500: return Fore.YELLOW
    if 500 <= status < 600: return Fore.RED
    return Fore.WHITE

def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def extract_title(html):
    m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if m:
        return m.group(1).strip()
    return None

def format_line(status, length, url, redirect=None, title=None):
    color = color_status(status)
    url_field = url.ljust(MAX_URL_LEN)
    line = f"{color}[{status}] {length} -> {url_field}"
    if redirect: line += f" ==> {redirect}"
    if title: line += f" | {title}"
    return line + Style.RESET_ALL

def parse_kv(data):
    if not data: return {}
    d = {}
    for kv in data.split(","):
        k, v = kv.split("=", 1)
        d[k] = v
    return d

def fuzz_replace(obj, word):
    if isinstance(obj, dict):
        return {k: fuzz_replace(v, word) for k, v in obj.items()}
    if isinstance(obj, str):
        return obj.replace("FUZZ", word)
    return obj

def load_wordlist(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return [x.strip() for x in f if x.strip()]

def output(text, pbar):
    if pbar: tqdm.write(text)
    else: print(text)

# -------------------------------
# Signal handling
# -------------------------------
def signal_handler(sig, frame):
    global ctrl_c_count, pause_flag, stop_flag
    ctrl_c_count += 1
    if ctrl_c_count == 1:
        pause_flag = True
        print("\n[!] Scan paused — press CTRL+C again to stop")
    else:
        stop_flag = True
        print("\n[!] Stopping scan...")
        sys.exit(0)

# -------------------------------
# Prepare export files
# -------------------------------
def prepare_exports(args):
    global file_handles, json_first, html_started, xlsx_wb, xlsx_ws
    if not args.output:
        return
    ts = get_timestamp()
    formats = [f.strip().lower() for f in args.output.split(",")]
    for fmt in formats:
        filename = f"fuzz_{ts}.{fmt}"
        if fmt == "txt" or fmt == "csv":
            f = open(filename, "a", encoding="utf-8", newline="" if fmt=="csv" else None)
            file_handles[fmt] = f
            if fmt=="csv":
                w = csv.writer(f)
                w.writerow(["status","length","url","redirect","title"])
        elif fmt == "json":
            f = open(filename, "w", encoding="utf-8")
            f.write("[\n")
            file_handles[fmt] = f
            json_first = True
        elif fmt == "html":
            f = open(filename, "w", encoding="utf-8")
            f.write("<html><head><meta charset='utf-8'><style>")
            f.write("table {border-collapse: collapse; width:100%; font-family: Arial, sans-serif;}")
            f.write("th, td {border: 1px solid #ccc; padding: 6px 10px; text-align: left;}")
            f.write("th {background-color: #f2f2f2;}")
            f.write("tr:hover {background-color:#f9f9f9;}")
            f.write("</style></head><body><table><tr><th>Status</th><th>Length</th><th>URL</th><th>Redirect</th><th>Title</th></tr>\n")
            file_handles[fmt] = f
            html_started = True
        elif fmt == "xlsx":
            global xlsx_wb, xlsx_ws
            xlsx_wb = Workbook()
            xlsx_ws = xlsx_wb.active
            xlsx_ws.append(["status","length","url","redirect","title"])
            file_handles[fmt] = f"fuzz_{ts}.xlsx"

# -------------------------------
# Export
# -------------------------------
def export_result(result, args):
    global json_first, html_started, xlsx_wb, xlsx_ws
    if not args.output: return
    formats = [f.strip().lower() for f in args.output.split(",")]
    for fmt in formats:
        try:
            if fmt=="txt":
                f = file_handles.get("txt")
                f.write(format_line(result["status"], result["length"], result["url"], result["redirect"], result["title"])+"\n")
                f.flush()
            elif fmt=="csv":
                f = file_handles.get("csv")
                w = csv.writer(f)
                w.writerow([result["status"], result["length"], result["url"], result["redirect"], result["title"]])
                f.flush()
            elif fmt=="json":
                f = file_handles.get("json")
                if not json_first: f.write(",\n")
                json.dump(result, f, indent=2)
                json_first = False
                f.flush()
            elif fmt=="html":
                f = file_handles.get("html")
                if 200<=result["status"]<300: color="green"
                elif 300<=result["status"]<400: color="cyan"
                elif 400<=result["status"]<500: color="orange"
                elif 500<=result["status"]<600: color="red"
                else: color="black"
                url_link = f'<a href="{result["url"]}" target="_blank">{result["url"]}</a>'
                redirect = result["redirect"] or ""
                title = result["title"] or ""
                f.write(f'<tr style="color:{color}"><td>{result["status"]}</td><td>{result["length"]}</td><td>{url_link}</td><td>{redirect}</td><td>{title}</td></tr>\n')
                f.flush()
            elif fmt=="xlsx":
                xlsx_ws.append([result["status"], result["length"], result["url"], result["redirect"], result["title"]])
                xlsx_wb.save(file_handles["xlsx"])
        except Exception as e:
            print(Fore.RED+f"[!] Export error ({fmt}): {e}"+Style.RESET_ALL)

# -------------------------------
# Worker queue
# -------------------------------
async def worker_queue(client, queue, args, pbar, start_time):
    global total_requests, timeout_counter
    while not queue.empty() and not stop_flag:
        word = await queue.get()
        while pause_flag:
            await asyncio.sleep(1)
        url = args.url.replace("FUZZ", word)
        params = fuzz_replace(args.params, word)
        data = fuzz_replace(args.data, word)
        headers = fuzz_replace(args.headers, word)
        try:
            r = await client.request(args.method, url, params=params, data=data, headers=headers)
            total_requests += 1

            # Progress
            if pbar:
                pbar.update(1)
                elapsed = time() - start_time
                rps = total_requests/elapsed if elapsed>0 else 0
                pbar.set_postfix_str(f"Req/s: {rps:.2f}")

            status = r.status_code
            length = len(r.text)
            redirect = r.headers.get("Location") if 300<=status<400 else None
            title = extract_title(r.text) if args.title else None

            # Filters
            if args.match_codes and status not in args.match_codes: pass
            if args.filter_codes and status in args.filter_codes: pass

            result = {"status": status,"length":length,"url":url,"redirect":redirect,"title":title}
            results.append(result)
            if not args.silent:
                output(format_line(status,length,url,redirect,title),pbar)
            export_result(result,args)

            timeout_counter=0
            if args.delay: await asyncio.sleep(args.delay)

        except (httpx.ReadTimeout,httpx.ConnectTimeout):
            timeout_counter+=1
            if timeout_counter>=3:
                tqdm.write(Fore.MAGENTA+"[!] 3 timeouts — pausing 10s"+Style.RESET_ALL)
                await asyncio.sleep(10)
                timeout_counter=0
        except Exception as e:
            tqdm.write(Fore.RED+f"[!] Error: {e} on {url}"+Style.RESET_ALL)
        finally:
            queue.task_done()

# -------------------------------
# Main async runner
# -------------------------------
async def run(args):
    global total_requests
    words = load_wordlist(args.wordlist)
    queue = asyncio.Queue()
    for w in words:
        queue.put_nowait(w)

    timeout = httpx.Timeout(10)
    start_time = time()
    async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=False, proxies=args.proxy) as client:
        pbar = tqdm(total=len(words), desc="Fuzzing") if args.progress else None
        tasks = [asyncio.create_task(worker_queue(client, queue, args, pbar, start_time)) for _ in range(args.threads)]
        await queue.join()
        for t in tasks: t.cancel()
        if pbar: pbar.close()

# -------------------------------
# Close exports
# -------------------------------
def finalize_exports():
    global file_handles, json_first, html_started, xlsx_wb
    if "json" in file_handles:
        f=file_handles["json"]; f.write("\n]"); f.close()
    if "html" in file_handles:
        f=file_handles["html"]; f.write("</table></body></html>"); f.close()
    if "txt" in file_handles: file_handles["txt"].close()
    if "csv" in file_handles: file_handles["csv"].close()
    if "xlsx" in file_handles and xlsx_wb: xlsx_wb.save(file_handles["xlsx"])

# -------------------------------
# Helpers
# -------------------------------
def parse_list(val):
    if not val: return None
    return [int(x) for x in val.split(",")]

# -------------------------------
# Main
# -------------------------------
def main():
    signal.signal(signal.SIGINT, signal_handler)
    parser = argparse.ArgumentParser(
        description="Async Web Fuzzer — high concurrency",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-u","--url",required=True,help="Target URL (use FUZZ as placeholder)")
    parser.add_argument("-w","--wordlist",required=True,help="Path to wordlist")
    parser.add_argument("-X","--method",default="GET",help="HTTP method")
    parser.add_argument("-t","--threads",type=int,default=50,help="Number of concurrent workers")
    parser.add_argument("--delay",type=float,default=0,help="Delay (seconds) between requests")
    parser.add_argument("-H","--headers",help="Custom headers: 'User-Agent=xyz'")
    parser.add_argument("-d","--data",help="POST data")
    parser.add_argument("-p","--params",help="Query parameters")
    parser.add_argument("-mc","--match-codes",help="HTTP codes to match, e.g., 200,301")
    parser.add_argument("-fc","--filter-codes",help="HTTP codes to filter")
    parser.add_argument("--proxy",help="Proxy URL (http:// or socks5://)")
    parser.add_argument("--progress",action="store_true",help="Show progress bar")
    parser.add_argument("--title",action="store_true",help="Fetch page <title>")
    parser.add_argument("-s","--silent",action="store_true",help="Silent output")
    parser.add_argument("-o","--output",help="Output formats: txt,json,csv,html,xlsx")
    args = parser.parse_args()
    args.headers=parse_kv(args.headers)
    args.data=parse_kv(args.data)
    args.params=parse_kv(args.params)
    args.match_codes=parse_list(args.match_codes)
    args.filter_codes=parse_list(args.filter_codes)

    prepare_exports(args)
    start=time()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Scan interrupted by user")
    print(f"\nFinished in {time()-start:.2f}s")
    finalize_exports()
    print("[!] All exports flushed")

if __name__=="__main__":
    main()
