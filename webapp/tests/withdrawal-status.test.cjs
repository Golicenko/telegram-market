const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8');
const code=source.slice(source.indexOf('  function withdrawalSubmissionText('),source.indexOf('  function renderTopupSelection('));
const render=vm.runInNewContext(`${code}; withdrawalSubmissionText`,{withdrawalStatusLabel:value=>value,formatNumber:value=>value});
test('withdrawal replay displays the current server state, not an assumed pending state',()=>{
  for(const status of ['pending','approved'])assert.match(render({id:'one',amount:'21.43',status}),/выплата ещё не завершена/);
  assert.match(render({id:'one',status:'paid'}),/Администратор подтвердил/);
  assert.doesNotMatch(render({id:'one',status:'paid'}),/Ожидает|Зарезервировано/);
  for(const status of ['rejected','cancelled'])assert.match(render({id:'one',status}),/Резерв возвращён/);
});
