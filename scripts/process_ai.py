"""Process saved Apple episodes without fetching Apple account data."""
import argparse
from sync import Notion, required, text_value, run_ai, safe_error


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    required('SILICONFLOW_API_KEY');required('DEEPSEEK_API_KEY')
    notion=Notion();notion.prepare()
    pages=list(notion.index('Episode','Eid').values())
    pages.sort(key=lambda p:(p['properties'].get('最近收听时间',{}).get('date') or {}).get('start',''),reverse=True)
    synced=[(page,{'id':text_value(page,'Eid').removeprefix('apple:'),
        'attributes':{'assetUrl':text_value(page,'音频'),'name':text_value(page,'标题')}}) for page in pages]
    failures=run_ai(notion,synced)
    if failures:raise RuntimeError(f'{failures} AI tasks failed; saved transcripts can resume')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('AI processing failed: '+safe_error(error));raise SystemExit(1)
