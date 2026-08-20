#!/usr/bin/env node
/**
 * Markdown -> PDF converter.
 *
 * Renders each .md file under an input directory to a PDF at the mirrored path
 * under an output directory.  Markdown becomes HTML via `marked` (GFM, so the
 * tables the doc generators emit survive) and is printed by a single headless
 * Chromium/Edge instance driven through `puppeteer-core` -- one browser for the
 * whole run, because launching one per file costs seconds each and these doc
 * sets run to thousands of files.
 *
 * Usage:
 *   node markdown-to-pdf.js <inputDir> <outputDir> [options]
 *
 * Options:
 *   --browser <path>     Chromium-based browser executable (Edge/Chrome).
 *   --css <path>         Extra stylesheet appended after the built-in print CSS.
 *   --concurrency <n>    Pages printed in parallel (default 4).
 *   --exclude <globs>    Comma-separated path globs to skip.
 *   --max <n>            Stop after n files (smoke tests).
 *   --force              Re-render even when the PDF is newer than the .md.
 *   --dry-run            List what would be written, print nothing.
 *   --quiet              Only warnings, errors and the summary.
 */

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Arguments
// ---------------------------------------------------------------------------

function parseArgs(argv) {
    const opts = {
        input: null,
        output: null,
        browser: null,
        css: null,
        concurrency: 4,
        exclude: [],
        max: 0,
        force: false,
        dryRun: false,
        quiet: false,
    };
    const positional = [];

    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i];
        switch (arg) {
            case '--browser': opts.browser = argv[++i]; break;
            case '--css': opts.css = argv[++i]; break;
            case '--concurrency': opts.concurrency = Math.max(1, parseInt(argv[++i], 10) || 1); break;
            case '--exclude':
                opts.exclude = String(argv[++i] || '')
                    .split(',')
                    .map(s => s.trim())
                    .filter(Boolean);
                break;
            case '--max': opts.max = Math.max(0, parseInt(argv[++i], 10) || 0); break;
            case '--force': opts.force = true; break;
            case '--dry-run': opts.dryRun = true; break;
            case '--quiet': opts.quiet = true; break;
            default:
                if (arg.startsWith('--')) {
                    throw new Error('Unknown option: ' + arg);
                }
                positional.push(arg);
        }
    }

    opts.input = positional[0];
    opts.output = positional[1];
    return opts;
}

// ---------------------------------------------------------------------------
// File discovery
// ---------------------------------------------------------------------------

// Never worth walking into these, and the output tree must not feed itself.
const ALWAYS_SKIP = new Set(['.git', 'node_modules', '.vs', '.vscode', 'Binaries', 'Intermediate']);

/** Glob -> RegExp over forward-slashed, input-relative paths. `**` spans separators. */
function globToRegExp(glob) {
    const specials = '\\^$+.()|{}[]';
    let out = '';
    for (let i = 0; i < glob.length; i++) {
        const c = glob[i];
        if (c === '*') {
            if (glob[i + 1] === '*') {
                out += '.*';
                i++;
                if (glob[i + 1] === '/') i++;
            } else {
                out += '[^/]*';
            }
        } else if (c === '?') {
            out += '[^/]';
        } else if (specials.indexOf(c) !== -1) {
            out += '\\' + c;
        } else {
            out += c;
        }
    }
    return new RegExp('^' + out + '$', 'i');
}

function collectMarkdown(inputDir, outputDir, excludeRegexes) {
    const files = [];
    const outputResolved = path.resolve(outputDir);

    (function walk(dir) {
        let entries;
        try {
            entries = fs.readdirSync(dir, { withFileTypes: true });
        } catch (err) {
            console.warn('[warn] cannot read ' + dir + ': ' + err.message);
            return;
        }

        for (const entry of entries) {
            const full = path.join(dir, entry.name);

            if (entry.isDirectory()) {
                if (ALWAYS_SKIP.has(entry.name)) continue;
                if (path.resolve(full) === outputResolved) continue; // don't re-print our own PDFs
                walk(full);
                continue;
            }

            if (!entry.isFile()) continue;
            if (path.extname(entry.name).toLowerCase() !== '.md') continue;

            const relative = path.relative(inputDir, full).split(path.sep).join('/');
            if (excludeRegexes.some(re => re.test(relative))) continue;

            files.push({ absolute: full, relative: relative });
        }
    })(inputDir);

    files.sort((a, b) => a.relative.localeCompare(b.relative));
    return files;
}

// ---------------------------------------------------------------------------
// Markdown -> HTML
// ---------------------------------------------------------------------------

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** First ATX H1, else the file name -- used for the <title> and page header. */
function deriveTitle(markdown, relativePath) {
    const match = markdown.match(/^#\s+(.+?)\s*$/m);
    if (match) return match[1].replace(/[*_`]/g, '').trim();
    return path.basename(relativePath, path.extname(relativePath));
}

const PRINT_CSS = [
    ':root { color-scheme: light; }',
    '* { box-sizing: border-box; }',
    'body {',
    '    margin: 0;',
    '    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;',
    '    font-size: 10.5pt;',
    '    line-height: 1.5;',
    '    color: #1b1f24;',
    '    background: #ffffff;',
    '    -webkit-print-color-adjust: exact;',
    '    print-color-adjust: exact;',
    '}',
    'h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 1.4em 0 0.5em; page-break-after: avoid; break-after: avoid; }',
    'h1 { font-size: 20pt; margin-top: 0; padding-bottom: 0.25em; border-bottom: 2px solid #d0d7de; }',
    'h2 { font-size: 15pt; padding-bottom: 0.2em; border-bottom: 1px solid #d8dee4; }',
    'h3 { font-size: 12.5pt; }',
    'h4 { font-size: 11pt; }',
    'h5, h6 { font-size: 10.5pt; color: #4a5259; }',
    'p, ul, ol, blockquote, table, pre { margin: 0 0 0.85em; }',
    'ul, ol { padding-left: 1.5em; }',
    'li { margin: 0.15em 0; }',
    'li > p { margin: 0.2em 0; }',
    'a { color: #0b5cad; text-decoration: none; word-break: break-word; }',
    'hr { height: 0; margin: 1.4em 0; border: 0; border-top: 1px solid #d0d7de; }',
    'strong { color: #10151a; }',
    'blockquote { padding: 0.2em 1em; color: #4a5259; border-left: 3px solid #d0d7de; }',
    'code, kbd, samp { font-family: "Cascadia Mono", Consolas, "Courier New", monospace; font-size: 0.88em; }',
    ':not(pre) > code {',
    '    padding: 0.12em 0.35em;',
    '    background: #f2f4f6;',
    '    border: 1px solid #e3e7eb;',
    '    border-radius: 3px;',
    '    word-break: break-word;',
    '}',
    'pre {',
    '    padding: 0.7em 0.9em;',
    '    background: #f6f8fa;',
    '    border: 1px solid #e1e5ea;',
    '    border-radius: 4px;',
    '    white-space: pre-wrap;',           // long engine signatures must wrap, not clip
    '    word-break: break-word;',
    '}',
    'pre > code { padding: 0; background: none; border: 0; }',
    'table { width: 100%; border-collapse: collapse; font-size: 9pt; table-layout: fixed; }',
    'thead { display: table-header-group; }',   // repeat headers across page breaks
    'tr { page-break-inside: avoid; break-inside: avoid; }',
    'th, td {',
    '    padding: 0.35em 0.5em;',
    '    text-align: left;',
    '    vertical-align: top;',
    '    border: 1px solid #d8dee4;',
    '    word-break: break-word;',
    '    overflow-wrap: anywhere;',
    '}',
    'th { background: #f2f4f6; font-weight: 600; }',
    'tbody tr:nth-child(even) { background: #fafbfc; }',
    'img { max-width: 100%; }',
    '.doc-source {',
    '    margin: 0 0 1.6em;',
    '    font-family: "Cascadia Mono", Consolas, monospace;',
    '    font-size: 8pt;',
    '    color: #6a737d;',
    '    word-break: break-all;',
    '}',
].join('\n');

function buildHtml(bodyHtml, title, sourceLabel, extraCss) {
    return [
        '<!doctype html>',
        '<html lang="en">',
        '<head>',
        '<meta charset="utf-8">',
        '<title>' + escapeHtml(title) + '</title>',
        '<style>' + PRINT_CSS + (extraCss || '') + '</style>',
        '</head>',
        '<body>',
        '<article>',
        bodyHtml,
        '<p class="doc-source">Source: ' + escapeHtml(sourceLabel) + '</p>',
        '</article>',
        '</body>',
        '</html>',
    ].join('\n');
}

/**
 * Point intra-doc links at the PDFs we are producing, so a converted tree stays
 * navigable.  Absolute URLs, protocol-relative URLs and fragments are left alone.
 */
function retargetMarkdownLinks(html) {
    return html.replace(/href="([^"]+)"/g, function (whole, href) {
        if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.indexOf('//') === 0 || href.charAt(0) === '#') {
            return whole;
        }
        return 'href="' + href.replace(/\.md(?=$|[?#])/i, '.pdf') + '"';
    });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
    let opts;
    try {
        opts = parseArgs(process.argv.slice(2));
    } catch (err) {
        console.error('[error] ' + err.message);
        return 2;
    }

    if (!opts.input || !opts.output) {
        console.error('Usage: node markdown-to-pdf.js <inputDir> <outputDir> [options]');
        return 2;
    }
    if (!fs.existsSync(opts.input) || !fs.statSync(opts.input).isDirectory()) {
        console.error('[error] input directory not found: ' + opts.input);
        return 1;
    }

    const log = opts.quiet ? function () {} : function () { console.log.apply(console, arguments); };

    let marked;
    try {
        marked = require('marked').marked;
    } catch (err) {
        console.error('[error] `marked` is not installed. Run the PowerShell wrapper, or: npm install --save-dev marked');
        return 1;
    }
    marked.setOptions({ gfm: true, breaks: false });

    let extraCss = '';
    if (opts.css) {
        if (!fs.existsSync(opts.css)) {
            console.error('[error] stylesheet not found: ' + opts.css);
            return 1;
        }
        extraCss = '\n' + fs.readFileSync(opts.css, 'utf8');
    }

    const excludeRegexes = opts.exclude.map(globToRegExp);
    const discovered = collectMarkdown(opts.input, opts.output, excludeRegexes);

    // Incremental by default: an existing PDF newer than its source is left alone.
    const jobs = [];
    let skipped = 0;
    for (const file of discovered) {
        const target = path.join(opts.output, file.relative.replace(/\.md$/i, '.pdf'));
        if (!opts.force && fs.existsSync(target)) {
            try {
                if (fs.statSync(target).mtimeMs >= fs.statSync(file.absolute).mtimeMs) {
                    skipped++;
                    continue;
                }
            } catch (err) { /* fall through and re-render */ }
        }
        jobs.push({ absolute: file.absolute, relative: file.relative, target: target });
        if (opts.max && jobs.length >= opts.max) break;
    }

    log('Found   : ' + discovered.length + ' markdown file(s)');
    log('Skipped : ' + skipped + ' up to date');
    log('To write: ' + jobs.length + ' PDF(s)');

    if (opts.dryRun) {
        for (const job of jobs) {
            log('  [dry-run] ' + job.relative + ' -> ' + path.relative(opts.output, job.target));
        }
        log('\nDry run - nothing written.');
        return 0;
    }
    if (jobs.length === 0) {
        log('\nNothing to do.');
        return 0;
    }

    let puppeteer;
    try {
        puppeteer = require('puppeteer-core');
    } catch (err) {
        console.error('[error] `puppeteer-core` is not installed. Run the PowerShell wrapper, or: npm install --save-dev puppeteer-core');
        return 1;
    }
    if (!opts.browser || !fs.existsSync(opts.browser)) {
        console.error('[error] browser executable not found: ' + (opts.browser || '<not supplied>'));
        console.error('        Pass --browser "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"');
        return 1;
    }

    const browser = await puppeteer.launch({
        executablePath: opts.browser,
        headless: true,
        args: ['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage'],
    });

    const headerFooterFont = 'font:7.5pt \'Segoe UI\',Arial,sans-serif;color:#8b949e;';
    const pdfOptions = {
        format: 'A4',
        printBackground: true,
        margin: { top: '18mm', right: '14mm', bottom: '16mm', left: '14mm' },
        displayHeaderFooter: true,
        headerTemplate: '<div style="width:100%;padding:0 14mm;' + headerFooterFont + '"><span class="title"></span></div>',
        footerTemplate: '<div style="width:100%;padding:0 14mm;' + headerFooterFont +
            '"><span class="pageNumber"></span> / <span class="totalPages"></span></div>',
    };

    const started = Date.now();
    const total = jobs.length;
    let done = 0;
    let failed = 0;
    let nextIndex = 0;

    async function worker() {
        const page = await browser.newPage();
        try {
            for (;;) {
                const index = nextIndex++;
                if (index >= total) break;
                const job = jobs[index];

                try {
                    const raw = fs.readFileSync(job.absolute, 'utf8').replace(/^\uFEFF/, '');
                    const title = deriveTitle(raw, job.relative);
                    const html = buildHtml(retargetMarkdownLinks(marked.parse(raw)), title, job.relative, extraCss);

                    fs.mkdirSync(path.dirname(job.target), { recursive: true });
                    await page.setContent(html, { waitUntil: 'load' });
                    await page.pdf(Object.assign({}, pdfOptions, { path: job.target }));

                    done++;
                    if (done % 25 === 0 || done === total) {
                        log('  [' + done + '/' + total + '] ' + job.relative);
                    }
                } catch (err) {
                    failed++;
                    console.warn('  [fail] ' + job.relative + ': ' + err.message);
                }
            }
        } finally {
            await page.close().catch(function () {});
        }
    }

    log('');
    const workers = [];
    for (let i = 0; i < Math.min(opts.concurrency, total); i++) workers.push(worker());
    await Promise.all(workers);
    await browser.close().catch(function () {});

    const seconds = ((Date.now() - started) / 1000).toFixed(1);
    console.log('\nWrote ' + done + ' PDF(s) in ' + seconds + 's' + (failed ? ', ' + failed + ' failed' : '') + '.');
    return failed ? 1 : 0;
}

main()
    .then(function (code) { process.exit(code); })
    .catch(function (err) {
        console.error('[error] ' + (err && err.stack ? err.stack : err));
        process.exit(1);
    });
