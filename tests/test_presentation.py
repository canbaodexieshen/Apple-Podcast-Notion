import copy
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import presentation as p
import sync


class MemoryNotion:
    def __init__(self):
        self.nodes={'root':{'id':'root','type':'page'}}
        self.contents={'root':[]}
        self.sequence=0
    def add(self,parent,block):
        self.sequence+=1
        block=copy.deepcopy(block)
        block['id']='b'+str(self.sequence)
        kind=block['type']
        nested=block[kind].pop('children',[])
        self.nodes[block['id']]=block
        self.contents.setdefault(parent,[]).append(block)
        self.contents[block['id']]=[]
        for child in nested:self.add(block['id'],child)
        return block
    def paginate(self,path,body=None):
        return iter(self.contents[path.split('/')[1]])
    def call(self,method,path,body=None):
        id=path.split('/')[1]
        if method=='GET':return copy.deepcopy(self.nodes[id])
        if method=='DELETE':
            for contents in self.contents.values():contents[:]=[b for b in contents if b['id']!=id]
            return {}
        if path.endswith('/children'):
            inserted=[self.add(id,b) for b in body['children']]
            position=body.get('position',{})
            if position.get('type') in ('start','after_block'):
                current=self.contents[id]
                current[:]=[b for b in current if b not in inserted]
                offset=0 if position['type']=='start' else next(i+1 for i,b in enumerate(current) if b['id']==position['after_block']['id'])
                current[offset:offset]=inserted
            return {'results':inserted}
        self.nodes[id].update(copy.deepcopy(body))
        return self.nodes[id]


class PresentationTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('mindmap_library.publish',return_value={'id':'map-page'});patcher.start();self.addCleanup(patcher.stop)
    def test_audio_update_omits_read_only_type(self):
        n=MemoryNotion();tabs=p.ensure_tabs(n,'root')
        block={'type':'audio','audio':{'type':'external','external':{'url':'https://example.test/a.mp3'}}}
        p.replace_tab(n,tabs['音频'],[block])
        with patch.object(n,'call',wraps=n.call) as call:
            p.replace_tab(n,tabs['音频'],[block])
            self.assertNotIn('type',call.call_args.args[2]['audio'])
    def legacy(self,n,title,text):
        n.add('root',{'type':'toggle','toggle':{'rich_text':sync.rich(title),'children':[p.text_block(text)]}})
    def test_four_native_tabs_are_idempotent(self):
        n=MemoryNotion()
        self.assertEqual(list(p.ensure_tabs(n,'root')),list(p.TAB_NAMES))
        p.ensure_tabs(n,'root')
        self.assertEqual(len(n.contents['root']),1)
    def test_migration_preserves_transcript_and_unrelated_notes(self):
        n=MemoryNotion()
        self.legacy(n,'Apple Podcasts · 逐字稿','已保存的文字')
        n.add('root',p.text_block('我的个人笔记'))
        p.migrate(n,'root')
        self.assertEqual(p.get_transcript(n,'root'),'已保存的文字')
        self.assertTrue(any(p.plain(b)=='我的个人笔记' for b in n.contents['root']))
        p.migrate(n,'root')
        self.assertEqual(p.get_transcript(n,'root'),'已保存的文字')
    @patch('presentation.upload_html')
    def test_outline_is_removed_only_after_markmap_attached(self,upload):
        n=MemoryNotion()
        self.legacy(n,'Apple Podcasts · 内容大纲','# 已有大纲')
        upload.side_effect=ValueError('upload failed')
        with self.assertRaises(ValueError):p.set_mindmap(n,'root','# 已有大纲')
        self.assertEqual(p.legacy_outline(n,'root'),'# 已有大纲')
        upload.side_effect=None
        fingerprint=hashlib.sha256((p.RENDER_VERSION+'|# 已有大纲').encode()).hexdigest()
        upload.return_value={'type':'embed','embed':{'url':'https://example.test/mindmap-'+fingerprint+'.html'}}
        p.set_mindmap(n,'root','# 已有大纲')
        self.assertEqual(p.legacy_outline(n,'root'),'')
        # An interrupted cleanup must resume even when the new HTML is saved.
        self.legacy(n,'Apple Podcasts · 内容大纲','# 已有大纲')
        p.set_mindmap(n,'root','# 已有大纲')
        self.assertEqual(p.legacy_outline(n,'root'),'')
        self.assertEqual(upload.call_count,2)  # failed once, uploaded once, then reused
    @patch('presentation.upload_html')
    def test_mindmap_upload_does_not_discard_existing_on_failure(self,upload):
        n=MemoryNotion();tabs=p.ensure_tabs(n,'root')
        p.replace_tab(n,tabs['脑图'],[p.text_block('existing')])
        upload.side_effect=ValueError('failed')
        with self.assertRaises(ValueError):p.set_mindmap(n,'root','# new')
        self.assertEqual(p.plain(n.contents[tabs['脑图']['id']][0]),'existing')
    def test_html_contains_no_external_scripts_and_escapes_script_close(self):
        html=p.markup('# </script><script>alert(1)</script>')
        self.assertNotIn('src="https://',html)
        self.assertIn('\\u003c/script\\u003e',html)
        self.assertIn('适应窗口',html)
        self.assertLess(len(html.encode()),5*1024*1024)
    def test_attachment_decodes_utf8_bytes_even_with_incorrect_http_charset(self):
        import requests
        expected='# 美国大选结果与特朗普胜选\n## 中文要点'
        response=requests.Response()
        response._content=p.markup(expected).encode('utf-8')
        response.encoding='ISO-8859-1'
        self.assertNotIn('美国大选',response.text)  # Reproduces the actual attachment bug.
        self.assertEqual(p.outline_from_html(response.content),expected)
    def test_old_mojibake_recovers_losslessly_without_changing_valid_text(self):
        expected='# 美国大选结果\n## 中文要点'
        self.assertEqual(p.restore_utf8_outline(expected.encode('utf-8').decode('latin1')),expected)
        for text in (expected,'# Café français','# plain English'):
            self.assertEqual(p.restore_utf8_outline(text),text)
    def test_native_mention_replaces_bare_url_and_preserves_personal_notes(self):
        n=MemoryNotion();tab=p.ensure_tabs(n,'root')['脑图']
        n.add(tab['id'],{'type':'embed','embed':{'url':'https://example.test/old.html'}})
        record='425c37fe-e474-81f7-a4ca-dfcfd1cf348f'
        n.add(tab['id'],p.text_block('我的个人笔记'))
        n.add(tab['id'],p.text_block('https://app.notion.com/p/'+record.replace('-','')+'?source=copy_link'))
        for _ in range(2):
            p.replace_brain_embed(n,tab,{'type':'embed','embed':{'url':'https://example.test/new.html'}})
            p.ensure_map_mention(n,tab,record)
        blocks=n.contents[tab['id']]
        self.assertEqual(len(blocks),3)
        self.assertEqual(blocks[1]['paragraph']['rich_text'][0]['mention']['page']['id'],record)
        self.assertEqual(p.plain(blocks[2]),'我的个人笔记')
    @patch('presentation.read_embed_outline',return_value='# 从HTML恢复')
    @patch('mindmap_library.lookup',return_value={'id':'root','properties':{}})
    def test_outline_recovers_after_markdown_property_is_removed(self,lookup,read):
        n=MemoryNotion()
        n.add('root',{'type':'heading_2','heading_2':{'rich_text':sync.rich('脑图'),'is_toggleable':True,
            'children':[{'type':'embed','embed':{'url':'https://example.test/map.html'}}]}})
        self.assertEqual(p.saved_outline(n,'episode'),'# 从HTML恢复')


if __name__=='__main__':unittest.main()
