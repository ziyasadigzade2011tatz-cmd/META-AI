import sys,tempfile,sqlite3,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.memory import Memory
from meta5.embeddings import Embeddings,pack,unpack,cosine

class EmbeddingTests(unittest.TestCase):
    def test_additive_backup_and_idempotency(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'memory.sqlite'
            with closing(sqlite3.connect(path)) as c,c:c.execute('CREATE TABLE facts(id TEXT PRIMARY KEY,kind TEXT,value TEXT UNIQUE,created REAL)');c.execute("INSERT INTO facts VALUES('old','fact','сохранённая запись',1)")
            m=Memory(path);self.assertEqual(m.records()[0]['value'],'сохранённая запись');backup=path.with_name(path.name+'.pre11');self.assertTrue(backup.exists())
            before=backup.read_bytes();Memory(path).records();self.assertEqual(before,backup.read_bytes())
            with closing(sqlite3.connect(backup)) as c:self.assertEqual(len(c.execute('PRAGMA table_info(facts)').fetchall()),4)
    def test_blob_and_cosine(self):
        vector=[1.,0.,.5];self.assertEqual(unpack(pack(vector),3),vector);self.assertAlmostEqual(cosine(vector,vector),1)
        self.assertEqual(cosine([0,0],[1,2]),0)
        with self.assertRaises(ValueError):pack([float('nan')])
    def test_index_mock_records_as_float32(self):
        with tempfile.TemporaryDirectory() as folder:
            m=Memory(Path(folder)/'memory.sqlite');pid=m.add('устойчивый факт')
            engine=Embeddings(m.path,client=lambda texts:[[1.,0.] for _ in texts]);self.assertEqual(engine.index(m.indexable()),1)
            with m.db() as c:
                row=c.execute('SELECT model,version,dimensions,typeof(vector) FROM embeddings').fetchone()
            self.assertEqual(row,('mock','test',2,'blob'))
    def test_model_unavailable_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            m=Memory(Path(folder)/'memory.sqlite');m.records()
            with patch.object(Embeddings,'metadata',side_effect=OSError):self.assertIsNone(Embeddings(m.path).vectors(['безопасный текст']))

if __name__=='__main__':unittest.main()
