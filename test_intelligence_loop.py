from core.intelligence.loop.intelligence_loop import IntelligenceLoop



loop = IntelligenceLoop()



results = loop.start(

    cycles=2,

    delay=1

)



print("="*50)
print("ATLAS INTELLIGENCE LOOP")
print("="*50)



for r in results:

    print(r)