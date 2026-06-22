const fs = require('fs');
const path = require('path');

let TurndownService;
try {
    TurndownService = require('turndown');
} catch (e) {
    console.error('Error: turndown package not found.');
    console.log('Install with: npm install turndown turndown-plugin-gfm');
    process.exit(1);
}

const gfm = require('turndown-plugin-gfm');

const htmlDir = process.argv[2];
const markdownDir = process.argv[3];

if (!htmlDir || !markdownDir) {
    console.error('Usage: node html-to-markdown.js <htmlDir> <markdownDir>');
    process.exit(1);
}

const turndownService = new TurndownService({
    headingStyle: 'atx',
    hr: '---',
    bulletListMarker: '-',
    codeBlockStyle: 'fenced',
    emDelimiter: '*',
});

turndownService.use(gfm.gfm);

turndownService.addRule('strikethrough', {
    filter: ['del', 's', 'strike'],
    replacement: (content) => {
        return '~~' + content + '~~';
    }
});

turndownService.addRule('mark', {
    filter: 'mark',
    replacement: (content) => {
        return '`' + content + '`';
    }
});

turndownService.addRule('customImage', {
    filter: 'img',
    replacement: (content, node) => {
        const alt = node.getAttribute('alt') || 'image';
        let src = node.getAttribute('src') || '';

        if (src.startsWith('file:///')) {
            src = src.replace('file:///', '').replace(/\\/g, '/');
        }

        return '![' + alt + '](' + src + ')';
    }
});

function convertHtmlToMarkdown(htmlPath) {
    try {
        const html = fs.readFileSync(htmlPath, 'utf-8');
        const markdown = turndownService.turndown(html);

        const fileName = path.basename(htmlPath);
        const relativeHtmlPath = path.relative(htmlDir, htmlPath);

        const frontMatter = '---\n' +
            'title: ' + fileName.replace(/\.html$/, '') + '\n' +
            'source: ' + relativeHtmlPath.replace(/\\/g, '/') + '\n' +
            'converted_at: ' + new Date().toISOString() + '\n' +
            '---\n\n';

        return frontMatter + markdown + '\n';
    } catch (error) {
        console.error('Error converting ' + htmlPath + ': ' + error.message);
        return null;
    }
}

function processDirectory(dir, outDir) {
    const files = fs.readdirSync(dir);
    let convertedCount = 0;

    files.forEach((file) => {
        const fullPath = path.join(dir, file);
        const stat = fs.statSync(fullPath);

        if (stat.isDirectory()) {
            const newOutDir = path.join(outDir, file);
            fs.mkdirSync(newOutDir, { recursive: true });
            convertedCount += processDirectory(fullPath, newOutDir);
        } else if (file.endsWith('.html')) {
            const markdown = convertHtmlToMarkdown(fullPath);
            if (markdown) {
                const markdownPath = path.join(outDir, file.replace(/\.html$/, '.md'));
                fs.writeFileSync(markdownPath, markdown, 'utf-8');
                console.log('✓ Converted: ' + file);
                convertedCount++;
            } else {
                console.log('✗ Failed: ' + file);
            }
        }
    });

    return convertedCount;
}

try {
    console.log('Converting HTML files to Markdown...\n');
    const count = processDirectory(htmlDir, markdownDir);
    console.log('\n✓ Successfully converted ' + count + ' file(s)');
} catch (error) {
    console.error('Error: ' + error.message);
    process.exit(1);
}
