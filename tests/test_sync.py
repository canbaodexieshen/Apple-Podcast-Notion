import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sync
import heatmap


def episode(eid='1', p=None):
    return {'id':eid,'attributes':{'name':'测试','durationInMilliseconds':1225000,
        'assetUrl':'https://example.com/audio.mp3','releaseDateTime':'2024-11-06T10:45:00Z'},
        'relationships':{'podcast':{'data':[{'id':'show'}]},
          **({'playback-position':{'data':[{'attributes':p}]}} if p is not None else {})}}


class AppleTests(unittest.TestCase):
    @patch('sync.get_json')
    def test_pagination_preserves_expansion(self,get):
        get.side_effect=[{'data':[{'id':'1'}],'next':'/v1/me/continue-playing/podcast-episodes?offset=abc%2B%2F'},
                         {'data':[{'id':'2'}]}]
        self.assertEqual(len(sync.apple_pages('/v1/me/recent/played/podcast-episodes',{})),2)
        query=parse_qs(urlsplit(get.call_args_list[1].args[0]).query)
        self.assertEqual(query['offset'],['abc+/'])
        self.assertIn('playback-position',query['include[podcast-episodes]'][0])

    @patch('sync.get_json')
    def test_next_cannot_exfiltrate_tokens(self,get):
        get.return_value={'data':[],'next':'https://evil.example/v1/me/x'}
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            sync.apple_pages('/v1/me/x',{'secret':'x'})
        self.assertEqual(get.call_count,1)

    @patch('sync.get_json')
    def test_repeated_cursor_stops(self,get):
        get.return_value={'data':[],'next':'/v1/me/x'}
        with self.assertRaisesRegex(ValueError,'Repeated'):
            sync.apple_pages('/v1/me/x',{})

    def test_saved_progress_survives_missing_recent_expansion(self):
        old=episode(p={'positionInMilliseconds':342000})
        merged=sync.merge_episodes({'1':old},{'1':episode()})
        self.assertEqual(sync.position(merged['1'])['positionInMilliseconds'],342000)

    def test_recent_progress_wins(self):
        merged=sync.merge_episodes({'1':episode(p={'positionInMilliseconds':1})},
                                   {'1':episode(p={'positionInMilliseconds':2})})
        self.assertEqual(sync.position(merged['1'])['positionInMilliseconds'],2)


class FakeNotion:
    def __init__(self,old=None):
        self.calls=[]
        self.old=old
        self.schemas={'Podcast':{}}
    def index(self,db,key):
        return {'apple:1':self.old} if db=='Episode' and self.old else {}
    def upsert(self,db,index,key,props):
        self.calls.append((db,key,props))
        p={'id':key,'properties':props}
        index[key]=p
        return p
    def call(self,*args):pass
    def section(self,*args):pass


class RecordTests(unittest.TestCase):
    def test_index_ignores_duplicate_legacy_ids(self):
        for db,key in [('Episode','Eid'),('Podcast','Pid')]:
            with self.subTest(db=db):
                n=object.__new__(sync.Notion)
                n.dbs={db:'database'}
                def page(id,value):
                    return {'id':id,'properties':{key:{'type':'rich_text','rich_text':[{'plain_text':value}]}}}
                n.paginate=Mock(return_value=iter([
                    page('old1','690a1e6aaaf2588eb7f1fff2'),
                    page('old2','690a1e6aaaf2588eb7f1fff2'),
                    page('new','apple:1000675890293')]))
                result=n.index(db,key)
                self.assertEqual(list(result),['apple:1000675890293'])
                self.assertEqual(result['apple:1000675890293']['id'],'new')
                self.assertEqual(n.paginate.call_args.args[1],
                    {'filter':{'property':key,'rich_text':{'starts_with':'apple:'}}})

    def test_index_still_rejects_duplicate_apple_ids(self):
        n=object.__new__(sync.Notion);n.dbs={'Episode':'database'}
        def page(id):
            return {'id':id,'properties':{'Eid':{'type':'rich_text','rich_text':[{'plain_text':'apple:123'}]}}}
        n.paginate=Mock(return_value=iter([page('a'),page('b')]))
        with self.assertRaisesRegex(ValueError,'Duplicate Episode.Eid: apple:123'):
            n.index('Episode','Eid')

    def test_podcast_source_is_optional(self):
        n=FakeNotion()
        sync.sync_records(n,{'show':{'attributes':{'name':'节目'}}},{},set())
        self.assertNotIn('来源',n.calls[0][2])
        self.assertEqual(n.calls[0][1],'apple:show')
        n=FakeNotion()
        n.schemas['Podcast']['来源']={'type':'rich_text'}
        sync.sync_records(n,{'show':{'attributes':{'name':'节目'}}},{},set())
        self.assertIn('来源',n.calls[0][2])
    def test_units_status_relations_and_source(self):
        n=FakeNotion()
        sync.sync_records(n,{'show':{'attributes':{'name':'节目'}}},
            {'1':episode(p={'positionInMilliseconds':342000,'completed':False,'recordedAtTimestamp':'2026-11-27T06:50:32Z'})},{'1'})
        db,key,p=n.calls[-1]
        self.assertEqual(key,'apple:1')
        self.assertEqual(p['时长']['number'],1225)
        self.assertEqual(p['播放位置']['number'],342)
        self.assertEqual(p['状态']['status']['name'],'在听')
        self.assertTrue(p['收藏']['checkbox'])
        self.assertEqual(p['Podcast']['relation'],[{'id':'apple:show'}])
        self.assertNotIn('收听时长',n.calls[0][2])

    def test_no_progress_does_not_clear_existing_progress(self):
        n=FakeNotion({'id':'existing','properties':{}})
        sync.sync_records(n,{}, {'1':episode()},set())
        p=n.calls[-1][2]
        self.assertNotIn('状态',p)
        self.assertNotIn('播放位置',p)

    def test_completed_with_zero_position(self):
        n=FakeNotion()
        sync.sync_records(n,{}, {'1':episode(p={'completed':True,'positionInMilliseconds':0})},set())
        self.assertEqual(n.calls[-1][2]['状态']['status']['name'],'听过')


class AITests(unittest.TestCase):
    def test_mermaid_escapes_model_syntax(self):
        result=sync.mermaid('# 主旨\n## A[危险]"\n### 子项')
        self.assertIn('flowchart LR',result)
        self.assertNotIn('A[危险]',result)
        self.assertIn('n2 --> n3',result)
    def test_empty_outline_rejected(self):
        with self.assertRaises(ValueError):sync.mermaid('not an outline')
    def test_rich_text_preserves_long_transcript(self):
        text='词'*30000
        runs=sync.rich(text)
        self.assertEqual(''.join(x['text']['content'] for x in runs),text)
        self.assertTrue(all(len(x['text']['content'])<=1800 for x in runs))
    def test_rich_text_rejects_oversize(self):
        with self.assertRaises(ValueError):sync.rich('x'*150001)
    @patch.dict(os.environ,{'SILICONFLOW_API_KEY':'','DEEPSEEK_API_KEY':''})
    def test_ai_optional(self):self.assertEqual(sync.run_ai(None,[]),0)
    @patch.dict(os.environ,{'SILICONFLOW_API_KEY':'secret','DEEPSEEK_API_KEY':''})
    @patch('sync.transcribe')
    def test_fingerprint_prevents_retranscription(self,transcribe):
        row=episode()
        import hashlib
        digest=hashlib.sha256(('1|'+row['attributes']['assetUrl']).encode()).hexdigest()
        p={'properties':{'转写指纹':{'type':'rich_text','rich_text':[{'plain_text':digest}]}}}
        self.assertEqual(sync.run_ai(None,[(p,row)]),0)
        transcribe.assert_not_called()


class TransportTests(unittest.TestCase):
    def test_prepare_never_patches_large_podcast_schema(self):
        n=object.__new__(sync.Notion)
        n.dbs={'Podcast':'podcast-db','Episode':'episode-db','Author':'author-db'}
        types={
          'Podcast':{'播客':'title','Pid':'rich_text','链接':'url','Description':'rich_text','作者':'relation'},
          'Episode':{'标题':'title','Eid':'rich_text','Podcast':'relation','音频':'rich_text','Description':'rich_text',
                     '发布时间':'date','时间戳':'number','时长':'number','链接':'url','状态':'status'},
          'Author':{'标题':'title'}}
        n.schemas={db:{name:{'type':kind} for name,kind in fields.items()} for db,fields in types.items()}
        n.schemas['Podcast']['演员']={'type':'multi_select','multi_select':{'options':[{'name':'x'*1035738}]}}
        n.schemas['Podcast']['作者']['relation']={'database_id':'author-db'}
        n.schemas['Episode']['Podcast']['relation']={'database_id':'podcast-db'}
        n.schemas['Episode']['状态']['status']={'options':[{'name':x} for x in ('未听','在听','听过')]}
        n.call=Mock()
        n.prepare(True)
        n.call.assert_called_once()
        self.assertEqual(n.call.call_args.args[1],'databases/episode-db')
        self.assertNotIn('演员',n.call.call_args.args[2]['properties'])
        n.call.reset_mock()
        n.prepare(False)
        n.call.assert_not_called()
    def test_unrelated_untitled_databases_are_ignored(self):
        n=object.__new__(sync.Notion);n.dbs={}
        n.paginate=lambda _:iter([
            {'type':'child_database','id':'a','child_database':{'title':'Untitled'}},
            {'type':'child_database','id':'b','child_database':{'title':'Untitled'}},
            {'type':'child_database','id':'c','child_database':{'title':'Episode'}}])
        n.discover('root')
        self.assertEqual(n.dbs,{'Episode':'c'})

    @patch('sync.time.sleep')
    @patch('sync.requests.request')
    def test_uncertain_create_is_not_retried(self,request,sleep):
        request.side_effect=sync.requests.Timeout()
        n=object.__new__(sync.Notion);n.last=0;n.headers={}
        with self.assertRaises(sync.requests.Timeout):n.call('POST','pages',{})
        self.assertEqual(request.call_count,1)
    @patch('sync.time.sleep')
    @patch('sync.requests.request')
    def test_rate_limit_retries(self,request,sleep):
        request.side_effect=[Mock(status_code=429,headers={'Retry-After':'1'}),Mock(status_code=200,ok=True,json=lambda:{'ok':True})]
        n=object.__new__(sync.Notion);n.last=0;n.headers={}
        self.assertEqual(n.call('GET','pages/x'),{'ok':True})
    @patch.dict(os.environ,{'NOTION_TOKEN':'very-secret-token'})
    def test_redact(self):
        self.assertNotIn('very-secret-token',sync.safe_error(ValueError('very-secret-token')))


class HeatmapTests(unittest.TestCase):
    def test_beijing_date_and_source_filter(self):
        def p(key):return {'properties':{'Eid':{'type':'rich_text','rich_text':[{'plain_text':key}]},
                          '进度更新时间':{'date':{'start':'2024-12-31T18:00:00Z'}}}}
        self.assertEqual(heatmap.history([p('apple:1'),p('xiaoyuzhou')]),{'2025-01-01':1})
    def test_empty_and_cross_year_site(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            heatmap.build({},root)
            self.assertTrue((root/'study_heatmap/main.svg').exists())
            heatmap.build({'2024-01-01':2,'2025-01-01':1},root)
            self.assertTrue((root/'old_heatmap/2024.svg').exists())
            text=(root/'heatmap.svg').read_text(encoding='utf-8')
            self.assertIn('2024: 2',text)
            self.assertNotIn('assetUrl',text)


if __name__=='__main__':unittest.main()
