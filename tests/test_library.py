import copy
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock
from test_presentation import MemoryNotion
import metadata
import mindmap_library as lib
import presentation
from sync import rich, text_value
import merge_episodes


class LibraryNotion(MemoryNotion):
    def __init__(self):
        super().__init__()
        self.dbs={'Episode':'episodes','思维导图':'maps'}
        self._map_schema={name:{'type':kind} for name,kind in {
            '名称':'title','思维导图封面':'files','播客单集':'relation',
            '脑图Markdown':'rich_text','内容指纹':'rich_text'}.items()}
        self._map_schema['播客单集']['relation']={'database_id':'episodes'}
        self.records={}
    def paginate(self,path,body=None):
        if path.startswith('databases/'):return iter(self.records.values())
        return super().paginate(path,body)
    def call(self,method,path,body=None):
        if path.startswith('pages'):
            if method=='POST':
                self.sequence+=1
                result={'id':'page'+str(self.sequence),'properties':{},'type':'page'}
                self.records[result['id']]=result
                self.contents[result['id']]=[]
            else:result=self.records[path.split('/')[1]]
            result['properties'].update(copy.deepcopy(body.get('properties',{})))
            for name,value in result['properties'].items():
                value.setdefault('type',next(iter(value)))
            result.update({k:v for k,v in body.items() if k!='properties'})
            return copy.deepcopy(result)
        return super().call(method,path,body)


class MetadataTests(unittest.TestCase):
    def test_existing_avatar_is_preserved(self):
        n=Mock();a={'id':'a','icon':{'type':'external','external':{'url':'https://avatar'}}}
        self.assertFalse(metadata.fill_author_icon(n,a,['https://work']))
        n.call.assert_not_called()
    def test_avatar_then_work_then_microphone(self):
        for profile,works,expected in [
            ({'头像':{'type':'url','url':'https://avatar'}},['https://work'],'https://avatar'),
            ({},['https://work'],'https://work'),({},[],None)]:
            n=Mock();a={'id':'a','properties':profile}
            metadata.fill_author_icon(n,a,works)
            icon=n.call.call_args.args[2]['icon']
            self.assertEqual(icon.get('external',{}).get('url'),expected)
    def test_date_rename_keeps_property_id(self):
        n=Mock();n.schemas={'Episode':{'收听时间':{'type':'date','id':'original'}}};n.dbs={'Episode':'e'}
        metadata.prepare_episode_fields(n,True)
        props=n.call.call_args.args[2]['properties']
        self.assertEqual(props['original'],{'name':'最近收听时间'})
        self.assertNotIn('收听时间',props)
    def test_current_date_field_is_not_recreated(self):
        n=Mock();n.schemas={'Episode':{'最近收听时间':{'type':'date'},
            '收听进度':{'type':'formula','formula':{'expression':metadata.PROGRESS_FORMULA}}}};n.dbs={'Episode':'e'}
        metadata.prepare_episode_fields(n,True)
        n.call.assert_not_called()


class LibraryTests(unittest.TestCase):
    def test_outline_keeps_skipped_heading_levels(self):
        title,nodes=lib.outline_tree('# 标题\n## 一\n#### 深层\n## 二')
        self.assertEqual(title,'标题')
        self.assertEqual(nodes[0]['children'][0]['label'],'深层')
        self.assertEqual(nodes[1]['label'],'二')
    def test_interrupted_tree_resumes_without_duplicates(self):
        n=MemoryNotion();_,nodes=lib.outline_tree('# 总结\n## 一\n### 子\n## 二')
        n.add('root',{'type':'heading_2','heading_2':{'rich_text':rich('一'),'is_toggleable':True}})
        self.assertTrue(lib.tree_prefix(n,'root',nodes))
        lib.resume_tree(n,'root',nodes)
        lib.resume_tree(n,'root',nodes)
        self.assertEqual([presentation.plain(b) for b in n.contents['root']],['一','二'])
        self.assertEqual(len(n.contents[n.contents['root'][0]['id']]),1)
    @patch('presentation.upload_html',return_value={'type':'embed','embed':{'type':'file_upload','file_upload':{'id':'html'}}})
    @patch('mindmap_library.upload_png',return_value={'type':'file_upload','file_upload':{'id':'png'}})
    @patch('render_mindmap.screenshot',return_value=(b'png',{'nodes':2,'width':100,'height':100}))
    def test_publish_updates_one_record_and_refreshes_cover(self,render,upload,html):
        n=LibraryNotion()
        for _ in range(2):lib.publish(n,'episode','# AI大标题\n## 分支')
        self.assertEqual(len(n.records),1)
        self.assertEqual(render.call_count,2)
        record=next(iter(n.records.values()))
        self.assertEqual(record['cover']['file_upload']['id'],'png')
        self.assertEqual(record['properties']['思维导图封面']['files'][0]['file_upload']['id'],'png')
        self.assertEqual(record['properties']['播客单集']['relation'],[{'id':'episode'}])
        blocks=n.contents[record['id']]
        self.assertEqual([b['type'] for b in blocks],['heading_2','heading_1'])
        self.assertEqual([presentation.plain(b) for b in blocks],['脑图','AI大标题'])
        self.assertTrue(all(b[b['type']]['is_toggleable'] for b in blocks))
        self.assertEqual(html.call_count,1)
        branch=n.contents[blocks[1]['id']][0]
        self.assertEqual(branch['type'],'heading_2')
        self.assertTrue(branch['heading_2']['is_toggleable'])
        self.assertNotIn('脑图Markdown',record['properties'])
    def test_markdown_property_is_kept_if_html_cannot_recover_it(self):
        n=Mock();n.dbs={'思维导图':'maps','Episode':'episodes'}
        n._map_schema={'脑图Markdown':{'id':'md'}}
        record={'id':'p','properties':{'脑图Markdown':{'type':'rich_text','rich_text':rich('# 唯一大纲')}}}
        n.paginate.return_value=iter([record])
        with patch('mindmap_library.ensure_database'),patch('presentation.library_outline',return_value=''):
            with self.assertRaisesRegex(ValueError,'kept to preserve'):
                lib.retire_markdown_property(n)
        n.call.assert_not_called()
    def test_markdown_property_removal_is_verified_and_idempotent(self):
        n=Mock();n.dbs={'思维导图':'maps','Episode':'episodes'}
        n._map_schema={'脑图Markdown':{'id':'md'}}
        record={'id':'p','properties':{'脑图Markdown':{'type':'rich_text','rich_text':rich('# 已保存大纲')}}}
        n._map_records={'episode':record}
        n.paginate.return_value=iter([record])
        with patch('mindmap_library.ensure_database'),patch('presentation.library_outline',return_value='# 已保存大纲'):
            lib.retire_markdown_property(n)
            lib.retire_markdown_property(n)
        n.call.assert_called_once_with('PATCH','databases/maps',{'properties':{'md':None}})
        self.assertNotIn('脑图Markdown',record['properties'])
    def test_heading_levels_are_preserved_including_fourth_level(self):
        n=MemoryNotion();_,nodes=lib.outline_tree('# 总结\n## 二级\n### 三级\n#### 四级')
        lib.append_tree(n,'root',nodes)
        parent='root'
        for level in (2,3,4):
            block=n.contents[parent][0]
            self.assertEqual(block['type'],'heading_'+str(level))
            self.assertTrue(block[block['type']]['is_toggleable'])
            parent=block['id']


class RealRendererTests(unittest.TestCase):
    def test_default_view_is_fully_expanded_and_fits_resized_iframe(self):
        from playwright.sync_api import sync_playwright
        outline='# 总结\n'+''.join(f'## 分支{i}\n### 中文详细要点{i}\n#### 深层内容{i}\n' for i in range(8))
        with sync_playwright() as p:
            channel=os.getenv('MINDMAP_BROWSER_CHANNEL')
            browser=p.chromium.launch(headless=True,**({'channel':channel} if channel else {}))
            try:
                page=browser.new_page(viewport={'width':1100,'height':850})
                page.set_content(presentation.markup(outline))
                page.evaluate('window.podcastMindmap.ready')
                def check():
                    return page.evaluate('''() => {
                        const svg=document.getElementById('map').getBoundingClientRect();
                        const nodes=[...document.querySelectorAll('.markmap-foreign')];
                        return {nodes:nodes.length,fit:nodes.every(n=>{
                            const r=n.getBoundingClientRect();
                            return r.left>=svg.left-1 && r.right<=svg.right+1 && r.top>=svg.top-1 && r.bottom<=svg.bottom+1;
                        }),height:svg.height};
                    }''')
                initial=check()
                self.assertEqual(initial['nodes'],25)
                self.assertTrue(initial['fit'])
                page.set_viewport_size({'width':650,'height':360})
                page.wait_for_timeout(600)
                resized=check()
                self.assertEqual(resized['nodes'],25)
                self.assertTrue(resized['fit'])
                self.assertEqual(resized['height'],360)
                # Notion loads HTML inside tabs/toggles which can start hidden.
                page.set_content(presentation.markup(outline).replace('<body>','<body style="display:none">'))
                page.evaluate('window.podcastMindmap.ready')
                page.evaluate('document.body.style.display="block"')
                page.wait_for_timeout(700)
                revealed=check()
                self.assertEqual(revealed['nodes'],25)
                self.assertTrue(revealed['fit'])
            finally:browser.close()
    def test_actual_bundle_expands_all_nodes_and_wraps_long_chinese(self):
        from render_mindmap import screenshot
        outline='# 总结\n'+''.join('## 分支%d\n### %s\n'%(i,'这是需要完整展示的中文要点'*10) for i in range(8))
        png,bounds=screenshot(presentation.markup(outline))
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertGreaterEqual(bounds['nodes'],17)
        self.assertGreater(bounds['height'],1000)


class LegacyMergeTests(unittest.TestCase):
    def test_large_backlink_is_merged_from_small_forward_side(self):
        n=Mock();n.dbs={'Episode':'e','Podcast':'p'}
        properties={'Eid':{'id':'eid','type':'rich_text','rich_text':rich('eid')},
                    'Podcast':{'id':'forward','type':'relation','relation':[{'id':'p1'}]}}
        a={'id':'a','properties':properties};b={**a,'id':'b'}
        programme={'id':'p1','properties':{'Episodes':{'id':'reverse','type':'relation',
            'has_more':True,'relation':[{'id':'b'}]}}}
        n.paginate.side_effect=[iter([a,b]),iter([]),iter([]),iter([programme]),iter([]),iter([a])]
        schema={'Episodes':{'type':'relation','relation':{'database_id':'e',
            'dual_property':{'synced_property_id':'forward'}}}}
        n.call.side_effect=lambda method,path,body=None: {'properties':schema if path=='databases/p' else {}}
        with tempfile.TemporaryDirectory() as folder:
            merge_episodes.merge(n,'eid','a',Path(folder)/'backup.json')
        self.assertIn(unittest.mock.call('PATCH','pages/b',{'properties':{'Podcast':{'relation':[]}}}),n.call.call_args_list)
        self.assertFalse(any(c.args[:2]==('PATCH','pages/p1') for c in n.call.call_args_list))

    def test_different_notes_are_not_silently_merged(self):
        n=Mock();n.dbs={'Episode':'e'}
        a={'id':'a','properties':{'笔记':{'type':'rich_text','rich_text':rich('我的笔记')}}}
        b={'id':'b','properties':{'笔记':{'type':'rich_text','rich_text':rich('另一份')}}}
        n.paginate.side_effect=[iter([a,b]),iter([]),iter([])]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'properties differ'):
                merge_episodes.merge(n,'eid','a',Path(folder)/'backup.json')
        n.call.assert_not_called()
    def test_identical_empty_duplicate_is_backed_up_then_soft_archived(self):
        n=Mock();n.dbs={'Episode':'e'}
        a={'id':'a','properties':{'Eid':{'type':'rich_text','rich_text':rich('eid')}}}
        b={**a,'id':'b'}
        n.paginate.side_effect=[iter([a,b]),iter([]),iter([]),iter([a])]
        n.call.return_value={'properties':{}}
        with tempfile.TemporaryDirectory() as folder:
            backup=Path(folder)/'backup.json'
            self.assertEqual(merge_episodes.merge(n,'eid','a',backup)['id'],'a')
            self.assertTrue(backup.exists())
        self.assertIn(unittest.mock.call('PATCH','pages/b',{'archived':True}),n.call.call_args_list)


if __name__=='__main__':unittest.main()
