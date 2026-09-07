Diese POC muss mit diese Modellen getest werden: 

LLM: qooba/qwen3-coder-30b-a3b-instruct
Emebddings: embeddings/multilingual-e5-large
vLLM: granite4.1:30b

Ich muss die LiteLLM proxy nutzen als einen lösung. Docker kann zu host network verbinden und den 
liteLLM url verwenden. 


werde ich den prozess nochmals ausführen. aber von root, und erwarte ich einen graph. Wo ich ein bisschen sense 
machen kann. 

Mann kann testen nochmals: 
python docling-graph/scripts/process_via_api.py user-manual-books/handbuch_daten/handbuch/Betriebshandbuch_ZSD.pdf --url http://localhost:8080 --out out/remote-zsd

Jetzt es laüft, und ich möchte den visualization mit diesem daten ausführen nicht drin in docling. Aber lass uns mal sehen. 

