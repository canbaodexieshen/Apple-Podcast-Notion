"""Publish latest playback-position dates, not fabricated daily listening duration."""
import json
import shutil
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from sync import Notion, text_value, safe_error

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def history(pages):
    counts = Counter()
    for p in pages:
        if not text_value(p,'Eid').startswith('apple:'):
            continue
        stamp = p.get('properties',{}).get('进度更新时间',{}).get('date')
        if stamp:
            day = datetime.fromisoformat(stamp['start'].replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).date()
            counts[day.isoformat()] += 1
    return counts


def draw(counts, years, path):
    svg = ET.Element('{'+NS+'}svg', {'viewBox':f'0 0 1000 {60+len(years)*185}', 'role':'img', 'aria-label':'播客最新播放进度记录'})
    def element(kind,attrs,text=None,parent=svg):
        item=ET.SubElement(parent,'{'+NS+'}'+kind,attrs)
        item.text=text
        return item
    element('rect',{'width':'1000','height':'100%','fill':'#ffffff'})
    element('text',{'x':'25','y':'25','font-size':'15'},'Apple Podcasts · 播放进度记录')
    element('text',{'x':'25','y':'45','font-size':'11','fill':'#777'},'按每集最新进度的记录日期计数，并非每日收听时长；同步后日期可能变化。')
    positives=sorted(v for v in counts.values() if v>0)
    low=positives[len(positives)//3] if positives else 1
    high=positives[2*len(positives)//3] if positives else 2
    for i,year in enumerate(years):
        y=75+i*185
        total=sum(v for k,v in counts.items() if k.startswith(str(year)+'-'))
        element('text',{'x':'25','y':str(y),'font-size':'15'},f'{year}: {total} 条进度记录')
        first=date(year,1,1)
        start=first-timedelta(days=first.weekday())
        day=first
        while day.year==year:
            week=(day-start).days//7
            value=counts.get(day.isoformat(),0)
            color='#ebedf0' if not value else ('#ace7ae' if value<=low else '#69c16e' if value<=high else '#549f57')
            cell=element('rect',{'x':str(45+week*17),'y':str(y+30+day.weekday()*15),'width':'13','height':'13','rx':'2','fill':color,'data-date':day.isoformat()})
            element('title',{},f'{day.isoformat()} · {value} 条进度记录',cell)
            if day.day==1:
                element('text',{'x':str(45+week*17),'y':str(y+20),'font-size':'10'},str(day.month)+'月')
            day+=timedelta(days=1)
    ET.ElementTree(svg).write(path,encoding='utf-8',xml_declaration=True)


def build(counts, output):
    output.mkdir(parents=True,exist_ok=True)
    (output/'study_heatmap').mkdir(exist_ok=True)
    (output/'old_heatmap').mkdir(exist_ok=True)
    current=datetime.now(ZoneInfo('Asia/Shanghai')).year
    years=sorted({int(x[:4]) for x in counts}|{current})
    for year in years:
        target=output/'study_heatmap/main.svg' if year==current else output/f'old_heatmap/{year}.svg'
        draw(counts,[year],target)
    draw(counts,years,output/'heatmap.svg')
    (output/'study_heatmap/years.json').write_text(json.dumps({'current':current,'years':sorted(years,reverse=True)}),encoding='utf-8')
    shutil.copyfile(Path(__file__).resolve().parents[1]/'web/index.html',output/'index.html')
    (output/'.nojekyll').touch()


if __name__=='__main__':
    try:
        notion=Notion()
        pages=list(notion.paginate('databases/'+notion.dbs['Episode']+'/query',{}))
        build(history(pages),Path('site'))
        print('Static heatmap built; only dates and counts are public.')
    except Exception as e:
        print('Heatmap failed: '+safe_error(e))
        raise SystemExit(1)
