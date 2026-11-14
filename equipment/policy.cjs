const {createHash}=require('node:crypto');
const FIELDS=['sourceId','sourceUrl','title','description','category','make','model','condition','countryCode','city','listingType','priceMinor','currency','rentPeriod','imageUrl','imageRightsConfirmed'];
const DAY=86400000;
function urlKey(value){return createHash('sha256').update(`${value.sourceId}\n${value.sourceUrl}`).digest('hex');}
function url(value,hosts){
  try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&(!u.port||u.port==='443')&&hosts.includes(u.hostname)&&!u.hash;}catch{return false;}
}
function eligible(old,source,item){return source?.enabled===true&&(!old||old.status==='PUBLISHED'&&old.revision===item.expectedRevision);}
function clean(item,source,now){
  const raw=item.listing;
  if(item.outcome!=='VERIFIED'||item.evidence?.availability!=='AVAILABLE'||!Number.isSafeInteger(item.verifiedAtMs)||item.verifiedAtMs>now||now-item.verifiedAtMs>2*60*60*1000)throw Error('Fresh product availability evidence required');
  if(!raw||raw.sourceId!==source.id||!url(raw.sourceUrl,source.allowedHosts)||!url(item.evidence.url,source.allowedHosts))throw Error('Unapproved source URL');
  for(const [key,min,max]of[['title',3,140],['description',10,3000],['make',0,60],['model',0,80],['city',1,80]]){
    if(typeof raw[key]!=='string'||raw[key].trim().length<min||raw[key].length>max||/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(raw[key]))throw Error('Invalid '+key);
  }
  if(!['TOTAL_STATION','GNSS','LEVEL','LASER_SCANNER','ACCESSORIES','OTHER'].includes(raw.category)||!['SALE','RENT'].includes(raw.listingType)||!['','NEW','USED'].includes(raw.condition))throw Error('Invalid product classification');
  if(!/^[A-Z]{2}$/.test(raw.countryCode)||raw.countryCode!==source.countryCode)throw Error('Unverified country');
  if(raw.currency&&!/^[A-Z]{3}$/.test(raw.currency))throw Error('Invalid currency');
  if(raw.priceMinor!=null&&(!Number.isSafeInteger(raw.priceMinor)||raw.priceMinor<=0||raw.priceMinor>100000000000||!raw.currency))throw Error('Invalid price');
  if(raw.listingType==='RENT'&&raw.priceMinor!=null&&!['DAY','WEEK','MONTH'].includes(raw.rentPeriod))throw Error('Invalid rental period');
  const value=Object.fromEntries(FIELDS.map(k=>[k,raw[k]??(k==='priceMinor'?null:k==='imageRightsConfirmed'?false:'')]));
  if(value.imageUrl&&(!source.imageReuseAllowed||value.imageRightsConfirmed!==true||!url(value.imageUrl,source.imageHosts)))throw Error('Unapproved image');
  return {...value,expiresAtMs:now+30*DAY};
}
function filterKeys(value){const keys=new Set();for(const country of['',value.countryCode])for(const city of['',value.city.toLowerCase()]){
  if(city&&!country)continue;for(const type of['',value.listingType])for(const category of['',value.category])keys.add(JSON.stringify([country,city,type,category]));
}return [...keys];}
module.exports={eligible,clean,filterKeys,urlKey,DAY};
