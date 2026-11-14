const {test}=require('node:test'),assert=require('node:assert/strict');
const {eligible,clean,filterKeys,urlKey}=require('../policy.cjs');
const source={id:'source_test',enabled:true,allowedHosts:['supplier.test.com'],imageHosts:['supplier.test.com'],imageReuseAllowed:true,countryCode:'EG'};
function item(){return {outcome:'VERIFIED',expectedRevision:2,verifiedAtMs:1000,evidence:{availability:'AVAILABLE',url:'https://supplier.test.com/product/one'},listing:{sourceId:source.id,sourceUrl:'https://supplier.test.com/product/one',title:'Survey tripod',description:'Survey instrument tripod from the original supplier.',category:'ACCESSORIES',make:'',model:'',condition:'',countryCode:'EG',city:'Cairo',listingType:'SALE',priceMinor:12050,currency:'EGP',rentPeriod:'',imageUrl:'https://supplier.test.com/tripod.jpg',imageRightsConfirmed:true}};}
test('admin pause archive draft and concurrent edits always win',()=>{
  for(const status of ['PAUSED','ARCHIVED','DRAFT'])assert.equal(eligible({status,revision:2},source,item()),false);
  assert.equal(eligible({status:'PUBLISHED',revision:3},source,item()),false);
  assert.equal(eligible({status:'PUBLISHED',revision:2},{...source,enabled:false},item()),false);
  assert.equal(eligible({status:'PUBLISHED',revision:2},source,item()),true);
});
test('only fresh verified offers from authorized country and image host',()=>{
  assert.equal(clean(item(),source,1100).priceMinor,12050);
  assert.throws(()=>clean({...item(),verifiedAtMs:0},source,8_000_000));
  for(const changed of [{countryCode:'SA'},{sourceUrl:'https://foreign.test.com/x'},{imageUrl:'https://foreign.test.com/x.jpg'},{priceMinor:0},{priceMinor:1.5}])
    assert.throws(()=>clean({...item(),listing:{...item().listing,...changed}},source,1100));
});
test('filter keys match the existing country city category contract',()=>{
  const keys=filterKeys(item().listing);
  assert.ok(keys.includes('["","","",""]'));
  assert.ok(keys.includes('["EG","","","ACCESSORIES"]'));
  assert.ok(keys.includes('["EG","cairo","SALE","ACCESSORIES"]'));
  assert.ok(!keys.includes('["","cairo","SALE","ACCESSORIES"]'));
  assert.equal(urlKey(item().listing),urlKey({...item().listing,title:'Another title'}));
});
