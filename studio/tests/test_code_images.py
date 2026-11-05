import base64,json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from vision import parse_image
from meta_studio.agent import Sessions

PNG='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jB8sAAAAASUVORK5CYII='
def call(action,**args):return json.dumps({'action':action,'args':args})

class CodeImageTests(unittest.TestCase):
    def test_real_image_header_required(self):
        self.assertTrue(parse_image(PNG))
        for image in ('https://example.org/image.png','data:image/png;base64,'+base64.b64encode(b'not an image').decode(),'data:image/svg+xml;base64,'+base64.b64encode(b'<svg/>').decode()):
            with self.assertRaises(ValueError):parse_image(image)
    def test_image_read_before_coding_without_persisting_raw_data(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);observed=[];actions=iter([call('write',path='index.html',content='<h1>Independent design</h1>'),call('check'),call('finish')])
            def client(messages):observed.append(json.dumps(messages));return next(actions)
            sessions=Sessions(root/'projects',root/'state',client=client,image_reader=lambda image,task:{'model':'local-vision-fixture','observations_untrusted':'Видна синяя панель.'})
            result=sessions.start({'task':'Создай страницу по приложенному скриншоту','image':PNG})
            deadline=time.monotonic()+5
            while sessions.active and time.monotonic()<deadline:time.sleep(.01)
            data=sessions.get(result['id']);self.assertEqual(data['status'],'completed')
            self.assertIn('IMAGE_OBSERVATIONS',observed[0]);self.assertNotIn(PNG,(root/'state'/(result['id']+'.json')).read_text('utf-8'))
            self.assertFalse(sessions.images);self.assertTrue(any(e['type']=='image_analyzed' for e in data['events']))
    def test_invalid_image_does_not_create_project(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=Sessions(root/'projects',root/'state')
            with self.assertRaises(ValueError):s.start({'task':'Создай проект','image':'https://private.example.org/photo'})
            self.assertEqual(list((root/'projects').iterdir()),[])

if __name__=='__main__':unittest.main()
