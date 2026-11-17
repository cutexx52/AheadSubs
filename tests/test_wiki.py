import json
from pathlib import Path
import tempfile
import unittest

from tools.wiki import ROOT, pages, write_pages


class WikiTests(unittest.TestCase):
    def test_live_readmes_produce_localized_navigation(self):
        output = pages()
        self.assertIn('/wiki/Home.zh-CN', output['Home.md'])
        self.assertIn('/main/docs/automation.zh-CN.md', output['Home.zh-CN.md'])
        self.assertIn('/main/docs/images/aheadsubs-overview.zh-CN.png', output['Home.zh-CN.md'])
        self.assertNotIn('/main/docs/images/aheadsubs-overview.png', output['Home.zh-CN.md'])

    def test_missing_markers_links_and_wrong_language_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/images').mkdir(parents=True)
            (root / 'docs/images/manifest.json').write_text(json.dumps({'images': [
                {'contains_text': True, 'english': 'en.png', 'chinese': 'cn.png'}]}))
            (root / 'en.png').touch()
            (root / 'cn.png').touch()
            template = '<!-- wiki:intro:start -->\n{}\n<!-- wiki:intro:end -->\n<!-- wiki:navigation:start -->\nDocs\n<!-- wiki:navigation:end -->'
            for name, image in [('README.md', 'en.png'), ('README.zh-CN.md', 'cn.png')]:
                (root / name).write_text(template.format(f'![Overview]({image})'))
            self.assertEqual(2, len(pages(root)))
            for bad in ('[Missing](gone.md)', '![Wrong](en.png)', '[Escape](../README.md)'):
                (root / 'README.zh-CN.md').write_text(template.format(bad))
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    pages(root)
            (root / 'README.zh-CN.md').write_text('No markers')
            with self.assertRaises(ValueError):
                pages(root)

    def test_repeated_generation_is_noop_and_preserves_other_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            other = destination / 'User-notes.md'
            other.write_text('Keep me')
            generated = pages(ROOT)
            self.assertEqual(2, len(write_pages(generated, destination)))
            self.assertEqual([], write_pages(generated, destination))
            self.assertEqual('Keep me', other.read_text())


if __name__ == '__main__':
    unittest.main()
