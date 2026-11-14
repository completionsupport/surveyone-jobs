// This collector only writes external supplier collections. It never reads users or sends FCM.
const fs=require('node:fs');
const path=require('node:path');
const admin=require('firebase-admin');
const policy=require('./policy.cjs');
const ROOT=__dirname;
const cfg=JSON.parse(fs.readFileSync(path.join(ROOT,'sources.json'),'utf8'));
const PROJECT='survey-one-f63a5';
const mode=process.argv[2];
const option=(name,fallback)=>{const i=process.argv.indexOf(name);return i<0?fallback:process.argv[i+1];};
const credentialPath=process.env.GOOGLE_APPLICATION_CREDENTIALS;
const key=JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT||(credentialPath?fs.readFileSync(credentialPath,'utf8'):'{}'));
if(key.project_id!==PROJECT)throw Error('Equipment collector requires the SurveyOne Firebase project');
admin.initializeApp({projectId:PROJECT,credential:admin.credential.cert(key)});
const db=admin.firestore();
const sources=db.collection('marketplaceExternalSources'),listings=db.collection('marketplaceExternalListings'),published=db.collection('marketplaceExternalPublished'),keys=db.collection('marketplaceExternalUrlKeys');

async function snapshot(){
  const approved=await Promise.all(cfg.sources.map(async config=>{const doc=await sources.doc(config.id).get();return doc.exists&&doc.get('enabled')?{...config,...doc.data(),id:doc.id}:null;}));
  const active=approved.filter(Boolean);const ids=new Set(active.map(s=>s.id));const selected=[];
  const maximum=Math.min(2000,Math.max(1,Number(option('--limit',120))));let after;
  // Query an existing single-field index. No unbounded scan or new index/IAM role required.
  while(selected.length<maximum){
    let query=listings.orderBy('lastVerifiedAtMs').limit(Math.min(200,maximum-selected.length+10));
    if(after)query=query.startAfter(after);
    const page=await query.get();if(page.empty)break;
    for(const doc of page.docs){const value=doc.data();
      if(value.lastVerifiedAtMs>Date.now()-12*60*60*1000)break;
      if(ids.has(value.sourceId)&&value.status==='PUBLISHED'&&(!value.collectorLastCheckedAtMs||value.collectorLastCheckedAtMs<Date.now()-6*60*60*1000))selected.push({id:doc.id,...Object.fromEntries([...Object.keys(value)].filter(k=>!['updatedBy','updatedAt'].includes(k)).map(k=>[k,value[k]]))});
      if(selected.length>=maximum)break;
    }
    after=page.docs.at(-1);if(after.get('lastVerifiedAtMs')>Date.now()-12*60*60*1000)break;
    if(page.size===0)break;
  }
  const slot=Math.floor(Date.now()/1800000)%4;
  active.forEach((s,i)=>{s.discover=s.discoveryEnabled!==false&&i%4===slot;});
  fs.writeFileSync(path.join(ROOT,'snapshot.json'),JSON.stringify({checkedAt:new Date().toISOString(),sources:active,listings:selected},null,2));
  console.log(JSON.stringify({sources:active.length,refreshCandidates:selected.length,discoverySources:active.filter(s=>s.discover).length}));
}

async function publish(){
  const plan=JSON.parse(fs.readFileSync(option('--plan',path.join(ROOT,'plan.json')),'utf8'));
  const report={checked:plan.items.length,verified:0,created:0,refreshed:0,unavailable:0,skipped:0,errors:[],countries:{},notificationsSent:0};
  const work=plan.items;
  let next=0;
  async function worker(){while(next<work.length){const item=work[next++];try{
    const sourceId=item.listing?.sourceId||item.sourceId,config=cfg.sources.find(s=>s.id===sourceId);
    if(!config){report.skipped++;continue;}
    const now=Date.now();
    const outcome=await db.runTransaction(async tx=>{
      const sourceDoc=await tx.get(sources.doc(sourceId));const source={...config,...sourceDoc.data(),id:sourceId};
      if(!sourceDoc.exists||!source.enabled)return 'SKIP';
      const raw=item.listing||{};
      const hash=item.outcome==='VERIFIED'?policy.urlKey(raw):null;
      const keyDoc=hash?await tx.get(keys.doc(hash)):null;
      if(!item.id&&!hash)return 'SKIP';
      const id=item.id||keyDoc?.get('listingId')||'external_'+hash.slice(0,32);
      const ref=listings.doc(id),oldDoc=await tx.get(ref),old=oldDoc.data();
      if(item.id&&item.id!==id||keyDoc?.exists&&keyDoc.get('listingId')!==id)return 'SKIP';
      // Existing URL found during discovery is left to its own revision-checked refresh.
      if(!item.id&&oldDoc.exists||!policy.eligible(old,source,item))return 'SKIP';
      if(!['VERIFIED','UNAVAILABLE'].includes(item.outcome)){
        if(old)tx.update(ref,{collectorLastCheckedAtMs:now,collectorAvailability:item.outcome});
        return 'SKIP';
      }
      if(item.outcome==='UNAVAILABLE'){
        if(!old)return 'SKIP';
        tx.delete(published.doc(id));
        tx.update(ref,{lastVerifiedAtMs:0,collectorLastCheckedAtMs:now,collectorAvailability:'UNAVAILABLE',updatedAtMs:now,revision:(old.revision||0)+1});
        return 'UNAVAILABLE';
      }
      const clean=policy.clean(item,source,now),revision=(old?.revision||0)+1,publishedAtMs=old?.publishedAtMs||now;
      tx.set(ref,{...old,...clean,status:'PUBLISHED',revision,urlKey:hash,lastVerifiedAtMs:now,publishedAtMs,
        createdAtMs:old?.createdAtMs||now,updatedAtMs:now,updatedAt:admin.firestore.FieldValue.serverTimestamp(),updatedBy:'equipment-collector',
        collectorLastCheckedAtMs:now,collectorAvailability:'AVAILABLE',collectorEvidence:{url:item.evidence.url,title:item.evidence.title,checkedAtMs:item.verifiedAtMs}});
      tx.set(published.doc(id),{...clean,status:'PUBLISHED',revision,lastVerifiedAtMs:now,publishedAtMs,filterKeys:policy.filterKeys(clean)});
      tx.set(keys.doc(hash),{listingId:id,sourceId});
      tx.set(ref.collection('audit').doc(),{action:old?'COLLECTOR_VERIFY':'COLLECTOR_PUBLISH',actor:'equipment-collector',createdAtMs:now,revision});
      return old?'REFRESHED':'CREATED';
    });
    if(outcome==='SKIP')report.skipped++;
    else if(outcome==='UNAVAILABLE')report.unavailable++;
    else{report.verified++;report[outcome==='CREATED'?'created':'refreshed']++;const c=item.listing.countryCode;report.countries[c]=(report.countries[c]||0)+1;}
  }catch(e){report.errors.push({sourceId:item.listing?.sourceId||item.sourceId,code:e.code||'VALIDATION',message:String(e.message).slice(0,180)});}}}
  await Promise.all(Array.from({length:4},worker));
  // Remove only already-invisible stale public projections. Private listings and admin history
  // remain intact; otherwise the browse API's bounded first page can contain only stale rows.
  report.staleProjectionsRemoved=0;
  for(let page=0;page<20;page++){
    const stale=await published.where('lastVerifiedAtMs','<=',Date.now()-14*policy.DAY).limit(200).get();
    if(stale.empty)break;
    const batch=db.batch();stale.docs.forEach(doc=>batch.delete(doc.ref,{lastUpdateTime:doc.updateTime}));
    try{await batch.commit();report.staleProjectionsRemoved+=stale.size;}catch(e){report.errors.push({code:e.code||'PRUNE_CONFLICT'});break;}
  }
  report.finishedAt=new Date().toISOString();
  fs.writeFileSync(path.join(ROOT,'last-run.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  if(report.errors.length)process.exitCode=1;
}
(async()=>{try{if(mode==='snapshot')await snapshot();else if(mode==='publish')await publish();else throw Error('Use snapshot or publish');}finally{await admin.app().delete();}})().catch(e=>{console.error('Equipment collector failed:',e.code||e.message);process.exitCode=1;});
