"""Reproducible import: all full extraction, matching and PNG generation run in Actions."""
import argparse,collections,concurrent.futures,hashlib,json,os,re,shutil,urllib.request
from pathlib import Path
import fitz
ROOT=Path(__file__).resolve().parents[1]
BOOK='dalizi-true';BASE='https://aokid666.github.io/zz-dalizi-2027/'
EXPECTED_SHA='4a5cc6fe7c24379391dfd3a0e968c0569e4a0cb470a906e0af3de1552205bae3'
def dump(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')))
def textnorm(t):return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',t).lower()
def lines(page,pn):
 out=[]
 for block in page.get_text('dict')['blocks']:
  for line in block.get('lines',[]):
   t=''.join(s['text'] for s in line['spans']).strip()
   if t and 45<line['bbox'][1]<775:out.append({'t':t,'p':pn,'b':list(line['bbox'])})
 return sorted(out,key=lambda l:(round(l['b'][1],1),l['b'][0]))
def refs(rows):
 out=[]
 for pn in dict.fromkeys(l['p'] for l in rows):
  ls=[l for l in rows if l['p']==pn];x=min(l['b'][0] for l in ls)-4;y=min(l['b'][1] for l in ls)-4;r=max(l['b'][2] for l in ls)+4;bot=max(l['b'][3] for l in ls)+4
  out.append({'page':pn,'b':[round(x,2),round(y,2),round(r-x,2),round(bot-y,2)]})
 return out
def cleanrows(rows):
 return [l for l in rows if not re.match(r'^(单选题|多选题)[（(]',l['t'])]
def sections(rows):
 # Preserve the source's exact text in separate named sections; never synthesize explanations.
 raw='\n'.join(l['t'] for l in rows)
 head=re.match(r'^\d+[、.．]\s*【答案】\s*[:：]?\s*[ABCD\s、,，]+',raw)
 if head:raw=raw[head.end():].lstrip()
 matches=list(re.finditer(r'【(解析|刷题笔记|真题思维点拨)】',raw));out=[]
 if not matches:return [{'k':'原书解析与笔记','t':raw}]
 if raw[:matches[0].start()].strip():out.append({'k':'原书补充说明','t':raw[:matches[0].start()].strip()})
 for i,m in enumerate(matches):
  text=raw[m.end():matches[i+1].start() if i+1<len(matches) else len(raw)].strip()
  if text:out.append({'k':m[1],'t':text})
 return out

def parse(doc):
 groups={};mode=None;year=None;allpages=[];read_sections=[]
 for pn,page in enumerate(doc,1):
  ls=lines(page,pn);allpages.append({'page':pn,'width':page.rect.width,'height':page.rect.height,'text':page.get_text()})
  for l in ls:
   t=l['t'];m=re.fullmatch(r'(20\d{2})\s*年考研政治真题(答案)?',t)
   if m and pn>=45:
    year=int(m[1]);mode='a' if m[2] else 'q';groups.setdefault(year,{'q':[],'a':[]});continue
   if 5<=pn<45 and re.match(r'^(特征[一二三四五六七]|经典题型[一二三]|专题[一二三四五])[：:]',t):
    read_sections.append({'title':t,'firstPage':pn})
   if year is not None:groups[year][mode].append(l)
 assert sorted(groups)==list(range(2015,2026)),list(groups)
 questions=[];anomalies=[]
 for year,group in groups.items():
  result={}
  for mode in ['q','a']:
   rows=cleanrows(group[mode]);heads=[]
   for i,l in enumerate(rows):
    if l['b'][0]>100:continue
    m=re.match(r'^(\d{1,2})[、.．]\s*(.*)',l['t'])
    if m and (mode=='q' or re.match(r'【答案】',m[2])):heads.append((i,int(m[1]),m[2]))
   nums=[num for _,num,_ in heads]
   assert nums==list(range(1,34)),f'{year}/{mode}: {nums}'
   result[mode]={num:(rows[i:heads[j+1][0] if j+1<len(heads) else len(rows)],first) for j,(i,num,first) in enumerate(heads)}
  for no in range(1,34):
   qr,first=result['q'][no];ar,_=result['a'][no];opts={};stem=[first];field=None
   for l in qr[1:]:
    t=l['t'];ms=list(re.finditer(r'(?:^|\s)([ABCD])[.．、]\s*',t))
    if ms:
     if t[:ms[0].start()].strip():
      if field:opts[field]+=t[:ms[0].start()].strip()
      else:stem.append(t[:ms[0].start()].strip())
     for j,m in enumerate(ms):
      field=m[1];assert field not in opts,f'duplicate option: {year}-{no}/{field}'
      opts[field]=t[m.end():ms[j+1].start() if j+1<len(ms) else len(t)].strip()
    elif field:opts[field]+=t
    else:stem.append(t)
   answer=re.search(r'【答案】\s*[:：]?\s*([ABCD](?:[\s、,，]*[ABCD])*)',ar[0]['t'])
   assert answer,f'missing answer {year}-{no}: {ar[0]["t"]}'
   answer=''.join(sorted(set(re.findall('[ABCD]',answer[1]))))
   assert set(opts)==set('ABCD') and all(opts.values()),f'{year}-{no}: {opts}'
   assert len(answer)==1 if no<=16 else len(answer)>=2,f'{year}-{no}: {answer}'
   q={'id':f'pr-{BOOK}-choice-{year}-{no:02}','bookId':BOOK,'type':'choice','source':'p','moduleIdx':10,'module':'考研政治历年真题','chapter':f'{year}年真题','chapterTitle':f'{year}年真题','section':'单项选择题' if no<=16 else '多项选择题','no':no,'originalNo':no,'examYear':str(year),'stem':'\n'.join(stem),'options':opts,'multi':no>=17,'answer':answer,'qRefs':refs(qr),'keyRefs':refs(ar),'analysis':sections(ar),'kPages':[],'sPages':[],'mRefs':[],'aPages':[],'aCrops':[]}
   if year==2025 and no==33:
    note='原PDF最后一页本题解析末句在“坚持开”处中断；此处按原书保留，未补写缺失内容。'
    q['analysis'].append({'k':'原文件完整性说明','t':note});q['sourceWarning']=note;anomalies.append({'questionId':q['id'],'page':280,'message':note})
   questions.append(q)
 return questions,allpages,read_sections,anomalies

def match_references(qs,site):
 docs={k:json.loads((site/'data'/f'lecture-{k}.json').read_text()) for k in ['k','s']}
 docs['m']={p['id']:p['text'] for p in json.loads((site/'data/manual-index.json').read_text())['pages']}
 for kind,pages in docs.items():
  ix=collections.defaultdict(set)
  for key,text in pages.items():
   text=textnorm(text)
   for n in range(len(text)-11):ix[text[n:n+12]].add(key)
  for q in qs:
   query=textnorm(q['stem']+'\n'+'\n'.join(q['options'][k] for k in q['answer']));grams={query[n:n+12] for n in range(len(query)-11)};scores=collections.Counter()
   for gram in grams:
    keys=ix.get(gram,())
    if len(keys)<=4:scores.update(keys)
   hits=[key for key,count in scores.most_common(2) if count>=6]
   q[{'k':'kPages','s':'sPages','m':'mRefs'}[kind]]=list(map(int,hits)) if kind!='m' else hits
 for q in qs:q['referenceMethod']='题干与正确选项中的连续相同原文匹配；未匹配资料明确显示没找到，请核对原文语境。'

def render_page(args):
 path,pn=args;doc=fitz.open(path);p=doc[pn-1];out=ROOT/'img'/BOOK/f'{pn:03}.png';out.parent.mkdir(parents=True,exist_ok=True)
 # Render once to lossless PNG at 216 dpi; do not rescale/recompress to JPEG or WebP.
 p.get_pixmap(matrix=fitz.Matrix(3,3),alpha=False).save(out)
 b=out.read_bytes();return {'page':pn,'ext':'png','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--site',type=Path,required=True);parser.add_argument('--render',action='store_true');a=parser.parse_args()
 pdf=ROOT/'pdf/dalizi-2027.pdf';blob=pdf.read_bytes();assert hashlib.sha256(blob).hexdigest()==EXPECTED_SHA
 doc=fitz.open(pdf);assert len(doc)==280
 qs,pages,read_sections,anomalies=parse(doc);assert len(qs)==363
 print('Extracted 363 questions: 176 single-choice, 187 multiple-choice, 11 years.',flush=True)
 match_references(qs,a.site)
 chapters=[{'key':f'考研政治历年真题 · {y}年真题','title':f'{y}年真题','firstPage':next(q['qRefs'][0]['page'] for q in qs if q['examYear']==str(y)),'count':33} for y in range(2015,2026)]
 source={'id':BOOK,'title':'大李子 · 历年真题与思维技巧（2015—2025）','url':BASE+'pdf/dalizi-2027.pdf','file':'27大李子真题思维技巧—选择题解题大招.pdf','pages':280,'sha256':EXPECTED_SHA,'count':363,'counts':{'choice':363},'chapters':chapters,'readSections':read_sections,'kind':'pastpaper','sourceBase':BASE,'pageSizes':[{'width':p['width'],'height':p['height']} for p in pages]}
 for q in qs:
  assert len(q['analysis']) and all(r['b'][2]>0 and r['b'][3]>0 and r['b'][1]+r['b'][3]<=pages[r['page']-1]['height'] for r in q['qRefs']+q['keyRefs'])
 dump(ROOT/'data/book.json',source);dump(ROOT/f'data/{BOOK}.json',{'bookId':BOOK,'questions':qs,'pages':pages})
 report={'questionCount':363,'years':list(range(2015,2026)),'single':sum(not q['multi'] for q in qs),'multiple':sum(q['multi'] for q in qs),'references':{k:sum(bool(q[k]) for q in qs) for k in ['kPages','sPages','mRefs']},'anomalies':anomalies,'pdfSha256':EXPECTED_SHA}
 if a.render:
  with concurrent.futures.ProcessPoolExecutor(max_workers=4) as ex:manifest=list(ex.map(render_page,[(str(pdf),p) for p in range(1,281)]))
  total=sum(p['bytes'] for p in manifest);assert total<800*1024*1024,f'Image repository needs splitting: {total}'
  dump(ROOT/'data/source-manifest.json',{'id':BOOK,'pdfSha256':EXPECTED_SHA,'pages':manifest,'render':{'dpi':216,'format':'png','lossless':True}})
  report['imageBytes']=total;report['imageCount']=len(manifest)
 dump(ROOT/'data/build-report.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)
main()
