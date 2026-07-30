To run fire-induced CLT layer fall-off simulation in ABAQUS, three files are provided.

## 📌 Files

**Delamination_control.py** is a python program controlling the deletion of the laminate once the temperature at the bond line reaches critical bond line temperature.

**layers.json** is to specify the parameters for heat transfer simulation and layer deletion. 

*watch*: The element set name that can trigger the delamination. Typically, it refers to the second layer.
*delete*: The element set name that should be deleted, i.e., the exposed layer.
*surface*: The bond line surface name.
*tcrit*: Critical bond line temperature.
*dur*: Maximum step of the simulation. 

**Delamination1** is the input file of ABAQUS, defining a five layer CLT model for heat transfer analysis.


## 📌 Run

Use ABAQUS command to run the python file.
```bash
📁 Basic input file (without .inp extension): Delamination1
📄 Layers for delamination (e.g., layers.json): layers.json
🔥 Fire temperature amplitude (e.g., ISO): ISO
🧠 Number of CPUs to use (default=8): 8
```
