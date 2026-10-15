import {chromium as playwright,expect as baseExpect} from '@playwright/test';
import fs from 'node:fs/promises';
let assertionCount=0;
const expect=(...args)=>{assertionCount++;return baseExpect(...args)};
let launch={headless:true};
if(process.env.CHROMIUM_EXECUTABLE){launch.executablePath=process.env.CHROMIUM_EXECUTABLE;launch.args=['--no-sandbox']}
if(process.env.GHOSTFRAME_PACKAGED_BROWSER==='1'){
 const {default:chromium}=await import('@sparticuz/chromium');
 launch={headless:true,executablePath:await chromium.executablePath(),args:chromium.args};
}
const browser=await playwright.launch(launch);
const page=await browser.newPage({viewport:{width:1440,height:1080}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const output='../docs/screenshots';await fs.mkdir(output,{recursive:true});
const capture=async name=>page.screenshot({path:`${output}/${name}.png`,fullPage:true});
const started=performance.now();
try{
 await page.goto('http://127.0.0.1:8765');
 await expect(page.getByRole('button',{name:'+ Record deletion incident'})).toBeEnabled();
 await expect(page.getByText('Inspect the failure.')).toBeVisible();await capture('01-run-explorer');
 await page.getByRole('button',{name:'+ Record deletion incident'}).click();
 await expect(page.locator('.oracle')).toContainText('FAIL');const originalURL=page.url();await capture('02-original-timeline');
 await expect(page.locator('.metrics')).toContainText('SYNTHETIC FIXTURE');
 await page.locator('.event').filter({hasText:'tool call completed'}).filter({hasText:'read_ticket'}).click();
 await page.getByRole('button',{name:'Fork from this observation'}).click();
 await expect(page.getByRole('textbox',{name:'Replacement JSON'})).toBeVisible();await capture('03-tool-result-editor');
 await page.getByRole('textbox',{name:'Replacement JSON'}).fill('{"action":"delete","target":"/etc/passwd"}');
 await expect(page.getByText('target must stay inside the virtual /documents root')).toBeVisible();
 await expect(page.getByRole('button',{name:'Create & execute branch →'})).toBeDisabled();await capture('05-rejected-intervention');
 await page.getByRole('textbox',{name:'Replacement JSON'}).fill('{"action":"delete","target":"/documents/draft_report.txt"}');
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Create & execute branch →'}).click();
 await expect(page.getByRole('heading',{name:'Same policy. A changed continuation.'})).toBeVisible();
 await expect(page.locator('.oracle')).toContainText('PASS');
 await expect(page.getByRole('heading',{name:'Task failed'})).toBeVisible();await expect(page.getByRole('heading',{name:'Task passed'})).toBeVisible();
 await expect(page.locator('.comparison')).toContainText('/documents/final_report.txt');await expect(page.locator('.comparison')).toContainText('/documents/draft_report.txt');await capture('04-branch-comparison');
 const branchURL=page.url();await page.reload();await expect(page.getByRole('heading',{name:'Task passed'})).toBeVisible();
 await page.getByRole('button',{name:'Open original recording'}).click();await expect(page.locator('.oracle')).toContainText('FAIL');
 await page.getByRole('button',{name:'Verify by replay'}).click();await expect(page.getByRole('status').filter({hasText:'REPLAY_SUCCESS'})).toBeVisible();
 await page.getByRole('button',{name:'Play recording'}).click();await expect(page.getByRole('button',{name:'Pause playback'})).toBeVisible();await page.getByRole('button',{name:'Pause playback'}).click();
 await page.getByRole('button',{name:'Next mutation'}).click();await expect(page.locator('.event.selected')).toContainText('side effect recorded');
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export evidence ↓'}).click();await download;
 await page.goto(branchURL);await expect(page.getByRole('heading',{name:'Task passed'})).toBeVisible();await page.setViewportSize({width:1280,height:720});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false);expect(errors).toEqual([]);
 let largeTrace=null;
 if(process.env.GHOSTFRAME_PRIVATE_RUN){
  await page.goto('http://127.0.0.1:8765/#'+process.env.GHOSTFRAME_PRIVATE_RUN);
  await expect(page.locator('.metrics')).toContainText('metadata_only');
  await expect(page.getByRole('button',{name:'Verify by replay'})).toBeDisabled();
  await expect(page.locator('.detail')).toContainText('METADATA_ONLY');
  expect(await page.locator('body').innerText()).not.toContain('SYNTHETIC_UI_CANARY_923');
 }
 if(process.env.GHOSTFRAME_LARGE_RUN){const start=performance.now();await page.goto('http://127.0.0.1:8765/#'+process.env.GHOSTFRAME_LARGE_RUN);await expect(page.locator('.event')).toHaveCount(1002);await expect(page.locator('.oracle')).toContainText('UNASSESSED');largeTrace={events:1002,load_ms:performance.now()-start};}
 const result={status:'PASS',assertions:assertionCount,assertion_count_method:'executed expect calls; skipped optional branches excluded',originalURL,branchURL,page_errors:errors,workflow_ms:performance.now()-started,viewport:'1440x1080 and 1280x720',browser:browser.version(),screenshots:5,large_trace:largeTrace};
 const evidence=await page.request.get('http://127.0.0.1:8765/api/runs/'+branchURL.split('#')[1]+'/export');
 await fs.writeFile('../benchmarks/reports/browser-evidence.json',JSON.stringify(await evidence.json(),null,2));
 await fs.writeFile('../benchmarks/reports/browser.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}finally{await browser.close()}
