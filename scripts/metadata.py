"""Compatible date/progress fields and conservative author image fallbacks."""
from sync import prop

PROGRESS_FORMULA = ('if(prop("状态") == "听过", "100%", '
    'if(prop("来源") == "Apple Podcasts" and not empty(prop("进度更新时间")) and prop("时长") > 0, '
    'format(round(min(1, max(0, prop("播放位置") / prop("时长"))) * 100)) + "%", ""))')


def prepare_episode_fields(notion, write):
    schema=notion.schemas['Episode']
    changes={}
    current=schema.get('最近收听时间')
    old=schema.get('收听时间')
    if current and current['type']!='date':
        raise ValueError('Episode.最近收听时间 must be date')
    if not current:
        if old and old['type']=='date':
            changes[old['id']]={'name':'最近收听时间'}
        elif old and old['type']=='created_time':
            if '同步创建时间' in schema:
                raise ValueError('Cannot preserve creation timestamp: 同步创建时间 already exists')
            changes[old['id']]={'name':'同步创建时间'}
            changes['最近收听时间']={'date':{}}
        elif not old:
            changes['最近收听时间']={'date':{}}
        else:
            raise ValueError('Episode.收听时间 has an unsupported type')
    progress=schema.get('收听进度')
    if progress and progress['type']!='formula':
        raise ValueError('Episode.收听进度 already exists with an incompatible type')
    if not progress or progress.get('formula',{}).get('expression')!=PROGRESS_FORMULA:
        changes['收听进度']={'formula':{'expression':PROGRESS_FORMULA}}
    if changes:
        print('Episode: prepare 最近收听时间 and 收听进度')
        if write:
            notion.call('PATCH','databases/'+notion.dbs['Episode'],{'properties':changes})


def image_url(image):
    if not image:return ''
    return image.get(image.get('type',''),{}).get('url','')


def fill_author_icon(notion, author, works):
    icon=author.get('icon')
    # Keep real images and custom icons. Upgrade only our microphone placeholder.
    if icon and not (icon.get('type')=='emoji' and icon.get('emoji')=='🎙️'):
        return False
    avatar=''
    for name in ('头像','作者头像','Avatar','avatar'):
        value=author.get('properties',{}).get(name,{})
        if value.get('type')=='url':avatar=value.get('url') or ''
        elif value.get('type')=='files' and value.get('files'):
            avatar=image_url(value['files'][0])
        if avatar:break
    # Prefer durable external artwork to temporary Notion file URLs.
    url=avatar or next((w for w in works if w), '')
    target={'type':'external','external':{'url':url}} if url else {'type':'emoji','emoji':'🎙️'}
    if target==icon:return False
    notion.call('PATCH','pages/'+author['id'],{'icon':target})
    author['icon']=target
    return True


def fill_all_author_icons(notion):
    works={}
    for show in notion.paginate('databases/'+notion.dbs['Podcast']+'/query',{}):
        artwork=image_url(show.get('cover')) or image_url(show.get('icon'))
        for author in show['properties'].get('作者',{}).get('relation',[]):
            works.setdefault(author['id'],[]).append(artwork)
    count=0
    for author in notion.paginate('databases/'+notion.dbs['Author']+'/query',{}):
        count+=fill_author_icon(notion,author,works.get(author['id'],[]))
    print(f'Author: {count} missing/placeholder icons filled; existing images preserved')
