import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sync
import ai_state


def page(**values):
    return {'id':'p','properties':{name:{'type':'rich_text','rich_text':sync.rich(value)} for name,value in values.items()}}


class AIStateTests(unittest.TestCase):
    @patch.dict('os.environ',{'SILICONFLOW_API_KEY':'a','DEEPSEEK_API_KEY':'b','AI_MAX_EPISODES':'1'})
    @patch('sync.deepseek',side_effect=ValueError('invalid outline'))
    @patch('sync.transcribe',return_value='保存的逐字稿')
    def test_map_failure_retains_transcribed_status_and_checkpoint(self,transcribe,deepseek):
        n=Mock()
        row={'id':'1','attributes':{'assetUrl':'https://publisher/audio'}}
        self.assertEqual(sync.run_ai(n,[(page(),row)]),1)
        updates=[call.args[2]['properties'] for call in n.call.call_args_list]
        self.assertTrue(updates[0]['转写指纹']['rich_text'])
        self.assertEqual(updates[-1]['AI状态']['status']['name'],'已转写')
        self.assertIn('deepseek_outline',sync.text_value({'properties':updates[-1]},'AI错误'))
    def test_backfill_classifies_checkpoints_and_old_errors(self):
        for values,expected in [({},'待处理'),({'转写指纹':'t'},'已转写'),
                ({'转写指纹':'t','脑图指纹':'m'},'已完成'),
                ({'AI状态旧记录':'音源受限，未转写：403'},'下载失败')]:
            self.assertEqual(ai_state.inferred_state(page(**values)),expected)
    def test_native_status_and_error_text_are_separate(self):
        n=Mock();ai_state.set_state(n,'p','下载失败','source HTTP 403')
        fields=n.call.call_args.args[2]['properties']
        self.assertEqual(fields['AI状态'],{'status':{'name':'下载失败'}})
        self.assertEqual(sync.text_value({'properties':fields},'AI错误'),'source HTTP 403')
    def test_native_status_is_not_parsed_as_rich_text(self):
        self.assertEqual(sync.text_value({'properties':{'AI状态':{'type':'status','status':{'name':'待处理'}}}},'AI状态'),'')


class NewOutlineTests(unittest.TestCase):
    def test_accepts_three_and_four_levels(self):
        for outline in ('# 总结\n## 分支\n### 具体事实','# 总结\n## 分支\n### 事实\n#### 细节'):
            sync.validate_new_outline(outline)
    def test_rejects_shallow_deep_and_skipped_levels(self):
        for outline in ('# 总结\n## 分支','# 总结\n## 分支\n### 事实\n#### 细节\n##### 太深',
                '# 总结\n### 跳级','# 总结\n## 一\n### 事实\n## 未展开分支'):
            with self.subTest(outline=outline),self.assertRaises(ValueError):sync.validate_new_outline(outline)
    @patch('sync.requests.post')
    def test_one_completed_output_format_correction_is_bounded(self,post):
        def response(text):return Mock(ok=True,json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':text}}]})
        post.side_effect=[response('# 总结\n## 太浅'),response('# 总结\n## 分支\n### 事实')]
        self.assertEqual(sync.deepseek('逐字稿','key'),'# 总结\n## 分支\n### 事实')
        self.assertEqual(post.call_count,2)
        post.side_effect=[response('# 总结\n## 太浅'),response('# 总结\n## 仍浅')]
        with self.assertRaises(ValueError):sync.deepseek('逐字稿','key')
        self.assertEqual(post.call_count,4)
    @patch.dict('os.environ',{'SILICONFLOW_API_KEY':'a','DEEPSEEK_API_KEY':'b','AI_MAX_EPISODES':'3'})
    @patch('sync.deepseek')
    @patch('sync.transcribe')
    def test_completed_legacy_map_is_not_regenerated_for_new_depth_rule(self,transcribe,deepseek):
        import hashlib
        row={'id':'1','attributes':{'assetUrl':'https://publisher/audio'}}
        tx=hashlib.sha256(('1|'+row['attributes']['assetUrl']).encode()).hexdigest()
        model=sync.os.getenv('DEEPSEEK_MODEL','deepseek-flash')
        mapping=hashlib.sha256((tx+'|'+model+'|v1').encode()).hexdigest()
        self.assertEqual(sync.run_ai(None,[(page(**{'转写指纹':tx,'脑图指纹':mapping}),row)]),0)
        deepseek.assert_not_called();transcribe.assert_not_called()


class WorkflowBoundaryTests(unittest.TestCase):
    def test_only_production_workflows_remain(self):
        root=Path(__file__).resolve().parents[1]/'.github/workflows'
        self.assertEqual({p.name for p in root.glob('*.yml')},{'sync.yml','ai.yml','pages.yml'})
        basic=(root/'sync.yml').read_text(encoding='utf-8')
        ai=(root/'ai.yml').read_text(encoding='utf-8')
        self.assertNotIn('SILICONFLOW_API_KEY',basic)
        self.assertNotIn('APPLE_BEARER_TOKEN',ai)
        self.assertIn("workflow_run.event == 'schedule'",ai)
        self.assertIn("cron: '0 17 * * *'",basic)
        for source in (basic,ai):
            self.assertNotIn('check_only',source);self.assertNotIn('skip_ai',source)


if __name__=='__main__':unittest.main()
