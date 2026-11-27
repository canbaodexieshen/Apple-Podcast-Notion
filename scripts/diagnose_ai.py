"""Probe only the three failed episodes; optional targeted recovery uses existing checkpoints."""
import argparse
from urllib.parse import urlsplit
import requests
from sync import Notion, text_value, run_ai, safe_error

IDS = ('1000675890293','1000802567395','1000675013007')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover',action='store_true',help='Resume AI and write recovered output for these three episodes')
    args=parser.parse_args()
    notion=Notion()
    rows=notion.index('Episode','Eid')
    synced=[]
    for eid in IDS:
        page=rows.get('apple:'+eid)
        if not page:
            print('Diagnostic: episode not synced: '+eid)
            continue
        url=text_value(page,'音频')
        if not url:
            print('Diagnostic: no audio URL: '+eid)
            continue
        print(f'Diagnostic {eid}: transcript_checkpoint={bool(text_value(page,"转写指纹"))}, '
              f'map_checkpoint={bool(text_value(page,"脑图指纹"))}',flush=True)
        try:
            # Match the downloader: ordinary GET, no Range or account headers.
            with requests.get(url,stream=True,timeout=(15,60)) as response:
                print(f'Diagnostic {eid}: audio HTTP={response.status_code}, '
                      f'host={urlsplit(response.url).hostname}, content_type={response.headers.get("content-type")}',flush=True)
        except requests.RequestException as e:
            print(f'Diagnostic {eid}: audio network error={type(e).__name__}',flush=True)
        synced.append((page,{'id':eid,'attributes':{'assetUrl':url}}))
    if args.recover:
        failed=run_ai(notion,synced)
        if failed:
            raise RuntimeError(f'{failed} targeted AI tasks still failed; inspect stage-specific diagnostics')


if __name__=='__main__':
    try:
        main()
    except Exception as e:
        print('AI diagnostic failed: '+safe_error(e))
        raise SystemExit(1)
