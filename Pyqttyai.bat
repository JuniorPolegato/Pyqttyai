cd "%USERPROFILE%/Documents/pyqttyai"
.venv\Scripts\activate
python main.py $@

rem pyinstaller main.py --name "Pyqttyai" --icon pyqttyai\images\pyqttyai.ico --noconsole --onefile --add-data "pyqttyai/images/;pyqttyai/images/" --collect-data faster_whisper --collect-data onnxruntime
rem pyinstaller main.py --name "Pyqttyai" --icon pyqttyai\images\pyqttyai.ico --noconsole --onefile --add-data "pyqttyai/images/;pyqttyai/images/" --collect-data faster_whisper --collect-data onnxruntime --collect-all optimum --collect-all openvino --collect-all transformers --collect-all librosa --hidden-import optimum.intel --hidden-import optimum.intel.openvino
