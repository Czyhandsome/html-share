"""Rebuild synthetic fixtures. These are NOT actual tournament results."""
import json
from pathlib import Path
ROOT=Path(__file__).parent
base={'schema_version':1,'event':{'name':'演示 · 羽毛球小组赛 + 淘汰赛（虚构数据）','snapshot_at':'2026-11-10T12:00:00+08:00','timezone':'Asia/Shanghai','venue_timezone':'Asia/Tokyo','back_link':'index.html'},'entries':[{'id':x,'name':name,'team':team} for x,name,team in [('a','示例选手甲','CHN'),('b','示例选手乙','JPN'),('c','示例选手丙','GER'),('d','示例组合丁 / 戊','CHN'),('e','示例组合己 / 庚','KOR'),('f','示例组合辛 / 壬','DEN')]],'sources':[{'id':'demo','url':'https://example.com/fictional-results','label':'虚构示例来源（仅用于演示）','kind':'official','family':'example.com'}], 'rules':{'badminton':{'best_of':3,'points':21,'win_by':2,'cap':30}},'groups':[],'matches':[]}
proof={'source_ids':['demo'],'verified_at':'2026-11-10T11:00:00+08:00'}
for gid, ids in [('A',['a','b','c']),('B',['d','e','f'])]:
 base['groups'].append({'id':gid,'name':gid+'组','entries':ids,'ranking':['wins','game_ratio','point_ratio']})
 for i,j in [(0,1),(0,2),(1,2)]:
  base['matches'].append({'id':f'{gid}-{i}-{j}','result_for':[ids[i],ids[j]],'group':gid,'round':gid+'组','slots':[{'entry':ids[i]},{'entry':ids[j]}],'rule':'badminton','status':'completed','games':[[21,16],[21,18]],'verification':proof})
for i,slots in enumerate([[{'group_rank':['A',1]},{'group_rank':['B',2]}],[{'group_rank':['B',1]},{'group_rank':['A',2]}]]):
 base['matches'].append({'id':'SF'+str(i+1),'result_for':(['a','e'] if i == 0 else ['d','b']),'round':'半决赛','slots':slots,'rule':'badminton','status':'completed','games':[[21,14],[22,20]],'verification':proof})
base['matches'].append({'id':'F','round':'决赛','slots':[{'winner':'SF1'},{'winner':'SF2'}],'rule':'badminton','status':'scheduled','scheduled_at':'2026-11-10T18:00:00+09:00'})
(ROOT/'groups-knockout.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n')
base['event']['name']='演示 · 乒乓球淘汰赛（虚构数据）'
base['event']['venue_timezone']='Europe/Berlin'
base['entries']=base['entries'][:4]
base['groups']=[]
base['rules']={'early':{'best_of':5,'points':11,'win_by':2},'final':{'best_of':7,'points':11,'win_by':2}}
base['matches']=[{'id':'SF1','result_for':['a','b'],'round':'半决赛','slots':[{'entry':'a'},{'entry':'b'}],'rule':'early','status':'completed','games':[[11,8],[9,11],[12,10],[11,4]],'verification':proof},{'id':'SF2','result_for':['c','d'],'round':'半决赛','slots':[{'entry':'c'},{'entry':'d'}],'rule':'early','status':'retired','winner':'d','games':[[11,9]],'in_progress_game':[3,5],'reason':'示例：选手丙因伤退赛，总比分不虚构成0–3','verification':proof},{'id':'F','round':'决赛','slots':[{'winner':'SF1'},{'winner':'SF2'}],'rule':'final','status':'scheduled','scheduled_at':'2026-11-10T14:00:00+01:00'}]
(ROOT/'knockout.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n')
try:
 import yaml
 (ROOT/'knockout.yaml').write_text(yaml.safe_dump(base,allow_unicode=True,sort_keys=False))
except ImportError: pass
