"""Native AI progress status, with lossless migration of old diagnostic text."""
import requests
from sync import prop, text_value, check_response

STATES=('待处理','下载失败','已转写','已完成')


def inferred_state(page):
    if text_value(page,'脑图指纹'):return '已完成'
    if text_value(page,'转写指纹'):return '已转写'
    old=text_value(page,'AI状态旧记录') or text_value(page,'AI状态') or text_value(page,'AI错误')
    if old.startswith(('音源受限','音源暂不可用')):return '下载失败'
    return '待处理'


def set_state(notion,page,state,error='',extra=None):
    if state not in STATES:raise ValueError('Unknown AI status')
    return notion.call('PATCH','pages/'+page,{'properties':{
        'AI状态':prop('status',{'name':state}),'AI错误':prop('rich_text',error),**(extra or {})}})


def prepare_status(notion):
    schema=notion.schemas['Episode']
    current=schema.get('AI状态')
    legacy=schema.get('AI状态旧记录')
    if schema.get('AI错误',{}).get('type','rich_text')!='rich_text':
        raise ValueError('AI错误 must be rich_text; existing data preserved')
    if current and current['type']=='rich_text':
        if legacy:raise ValueError('AI状态旧记录 already exists; originals preserved')
        notion.call('PATCH','databases/'+notion.dbs['Episode'],{'properties':{current['id']:{'name':'AI状态旧记录'}}})
        legacy=current;current=None
        print('AI status: preserved previous text; creating native status property',flush=True)
    if current and current['type']!='status':raise ValueError('AI状态 must be native status')
    if not current:
        headers={**notion.headers,'Notion-Version':'2026-03-11'}
        result=requests.get('https://api.notion.com/v1/databases/'+notion.dbs['Episode'],headers=headers,timeout=(15,90))
        check_response(result,'notion_ai_status_schema')
        sources=result.json().get('data_sources',[])
        if len(sources)!=1:raise ValueError('Expected one Episode data source; originals preserved')
        options=[{'name':name,'color':color,'group':group} for name,color,group in (
            ('待处理','gray','To-do'),('下载失败','red','To-do'),('已转写','blue','In progress'),('已完成','green','Complete'))]
        notion.call('PATCH','data_sources/'+sources[0]['id'],{'properties':{
            'AI状态':{'status':{'options':options}},'AI错误':{'rich_text':{}}}})
    elif not set(STATES)<={o['name'] for o in current['status']['options']}:
        raise ValueError('AI状态 requires 待处理 / 下载失败 / 已转写 / 已完成')
    elif 'AI错误' not in schema:
        notion.call('PATCH','databases/'+notion.dbs['Episode'],{'properties':{'AI错误':{'rich_text':{}}}})
    pages=list(notion.index('Episode','Eid').values())
    count=0
    for page in pages:
        old=text_value(page,'AI状态旧记录')
        status=page['properties'].get('AI状态',{}).get('status')
        if legacy or not status:
            error=old if old and old not in STATES else ''
            set_state(notion,page['id'],inferred_state(page),error)
            count+=1
    if count:print(f'AI status: initialized {count} records; verifying preserved diagnostics',flush=True)
    if legacy:
        # Non-Apple history must not lose diagnostic text from other integrations.
        all_pages=list(notion.paginate('databases/'+notion.dbs['Episode']+'/query',{}))
        unsafe=[p for p in all_pages if not text_value(p,'Eid').startswith('apple:') and text_value(p,'AI状态旧记录')]
        if not unsafe:
            for page in pages:
                actual=notion.call('GET','pages/'+page['id'])
                old=text_value(page,'AI状态旧记录')
                if actual['properties']['AI状态']['status']['name']!=inferred_state(page):
                    raise ValueError('AI status migration verification failed; old text preserved')
                if old and old not in STATES and text_value(actual,'AI错误')!=old:
                    raise ValueError('AI error migration verification failed; old text preserved')
            notion.call('PATCH','databases/'+notion.dbs['Episode'],{'properties':{'AI状态旧记录':None}})
    notion.schemas['Episode']=notion.call('GET','databases/'+notion.dbs['Episode'])['properties']
    print(f'AI status: native states ready; {count} existing Apple records initialized',flush=True)
