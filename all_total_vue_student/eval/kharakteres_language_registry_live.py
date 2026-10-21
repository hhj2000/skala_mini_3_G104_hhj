"""Isolated OpenAI/Ollama smoke for newly registered languages; real API usage.

Four model calls by default, six with --extended; live lexical
lookups, temporary spell DB. Not a linguistic accuracy benchmark. No user records.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
from kharakteres.models import GenerateRequest, SpellInput, LANGUAGES, LANGUAGE_SECTIONS
from kharakteres.generation import SpellGenerator
from kharakteres.store import SpellStore
from kharakteres.verification import verify_language


async def run(args):
    load_dotenv(ROOT/'.env')
    os.environ['LLM_BACKEND']=args.backend
    os.environ['SPELL_DICTIONARY_PROVIDER']='wiktapi'
    os.environ['LANGSMITH_TRACING']='false'
    os.environ['LANGCHAIN_TRACING_V2']='false'
    from agent.model_factory import _build_llms
    _,_,model=_build_llms('improved')
    model.num_predict=1536
    results=[]
    with tempfile.TemporaryDirectory(prefix='kharakteres-languages-') as tmp:
        store=SpellStore(Path(tmp)/'spells.sqlite')
        generator=SpellGenerator(args.backend,model,store)
        try:
            cases=[('포르투갈어로 만들어 주세요','pt','luz'),('핀란드어로 만들어 주세요','fi','valo'),('히브리어로 만들어 주세요','he','אור')] if args.extended else [('이탈리아어로 만들어 주세요','it','luce'),('고대 교회 슬라브어로 만들어 주세요','cu','свѣтъ')]
            for message,code,word in cases:
                choice=await generator.resolve_language(message)
                assert choice.resolved and choice.language==code,choice
                result=await generator.generate(GenerateRequest(prompt='작은 방을 조용히 비추는 짧은 빛의 주문',language=choice.language,elements=['light'],school='utility',limitations='열을 내지 않는다'))
                draft=SpellInput.model_validate(result['draft']).model_dump()
                saved=store.create(draft)
                assert store.get(saved['id'])['language']==code
                lexical=await verify_language({'language':code,'incantation':word})
                assert lexical['status']=='references_found',lexical
                from kharakteres.language_catalog import CATALOG
                assert lexical['sources'][0]['language']==(LANGUAGE_SECTIONS.get(code) or CATALOG.get(code)['english_name'])
                results.append({'message':message,'choice':choice.model_dump(),'draft':draft,'generation_steps':result['steps'],
                                'usage':result['usage'],'saved_and_read':True,'attested_word_lookup':lexical})
                print(code,'generation, persistence and lexical lookup passed',flush=True)
        finally: store.close()
    output={'checked_at':datetime.now(timezone.utc).isoformat(),'backend':args.backend,'model':model.name,
            'registered_count':len(LANGUAGES),'language_catalog':CATALOG.metadata(),'cases':results,
            'scope':'production graph and live lexical lookup, no model guard/audio/UI; not expert grammar/pronunciation validation'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['openai','ollama'],default='openai')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--extended',action='store_true')
    args=p.parse_args()
    if args.output.exists(): p.error('Use a new evidence file')
    asyncio.run(run(args))


if __name__=='__main__':main()
