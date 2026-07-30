# -*- coding: utf-8 -*-
"""
    abaqus python multi_delam_merge.py
"""

import argparse, os, re, json, time, subprocess, shutil
from contextlib import suppress


def rm_old(job):
    for ext in (".com",".dat",".log",".msg",".odb",".prt",".res",".sta",".pes",".lck",".sim",".stt",".mdl",".abq",".pac"):
        with suppress(Exception):
            os.remove(f"{job}{ext}")

def wait_done(job, poll=10, stable=3, timeout_h=240):
    odb, sta, lck = f"{job}.odb", f"{job}.sta", f"{job}.lck"
    sizes, deadline = [], time.time() + timeout_h*3600
    print(f">> Waiting for {job} to finish...")
    while time.time() < deadline:
        time.sleep(poll)
        if os.path.exists(sta):
            s = open(sta, "r", encoding="utf-8", errors="ignore").read().upper()
            if "COMPLETED" in s: return print(f"{job} has completed.")
            if any(x in s for x in ("ERROR","TERMINATED")):
                raise RuntimeError(f"{job} failed; check .sta/.msg")
        if os.path.exists(odb):
            sizes = (sizes + [os.path.getsize(odb)])[-stable:]
            if len(sizes)==stable and len(set(sizes))==1 and not os.path.exists(lck):
                return print("   - ODB stable")
    raise TimeoutError(f"Timeout waiting for {job}")

def run_and_wait(abaqus, job, inp, oldjob, cpus):
    rm_old(job)
    cmd = f'{abaqus} job={job} input={inp}'
    if oldjob: cmd += f' oldjob={oldjob}'
    cmd += f' cpus={cpus}'
    print(">>", cmd)
    subprocess.run(cmd, shell=True, check=True)
    wait_done(job)

def read_amp(inp, amp):
    txt = open(inp, encoding="utf-8", errors="ignore").read()
    m = re.search(rf"\*AMPLITUDE\s*,\s*NAME\s*=\s*{amp}\s*([\s\S]*?)(?:\n\*)", txt, re.I)
    if not m: raise RuntimeError(f"{amp} not found in {inp}")
    data = [tuple(map(float, ln.split(",")[:2])) for ln in m.group(1).splitlines() if "," in ln]
    return sorted(data, key=lambda x:x[0])

def rebase(data, tf, extend):
    for (t0,T0),(t1,T1) in zip(data[:-1], data[1:]):
        if t0<=tf<=t1: Ttf = T0+(T1-T0)*(tf-t0)/(t1-t0); break
    else: Ttf = data[-1][1]
    curve = [(0.0,Ttf)] + [(t-tf,T) for t,T in data if t>tf]
    curve.append((curve[-1][0]+extend, curve[-1][1]))
    return curve, Ttf

def write_restart(out, tf, step, inc, amp, curve, next_step, dur, delete, surf):
    lines = [
        f"** Auto-generated restart at t={tf:.3f} min",
        f"*RESTART, READ, STEP={step}, INC={inc}, END=NO",
        f"*AMPLITUDE, NAME={amp}",
        *[f"{t:.3f}, {T:.2f}" for t,T in curve],
        f"*STEP, NAME={next_step}, INC=10000",
        "*HEAT TRANSFER, END=PERIOD, DELTMX=800",
        f"0.01, {dur:.6f}, 1.E-09, 1.",
        "*MODEL CHANGE, REMOVE", delete,
        f"*SFILM, AMPLITUDE={amp}", f"{surf}, F, 1., 1.5",
        f"*SRADIATE, AMPLITUDE={amp}", f"{surf}, R, 1., 0.8",
        "*OUTPUT, FIELD", "*NODE OUTPUT","NT",
        "*ELEMENT OUTPUT, DIRECTIONS=YES","TEMP", "*END STEP",""
    ]
    open(out,"w",encoding="utf-8").write("\n".join(lines))
    print(f">> Wrote {out}")

def first_hit(odb_path, step_name, elset_watch, delete_set, tcrit):
    from odbAccess import openOdb
    odb = openOdb(odb_path, readOnly=True)
    try:
        step = odb.steps[step_name] if step_name in odb.steps else list(odb.steps.values())[-1]
        inst, aset = elset_watch.split(".", 1)
        region = odb.rootAssembly.instances[inst.upper()].elementSets[aset.upper()]
        for fr in step.frames:
            if "TEMP" not in fr.fieldOutputs: continue
            vals = fr.fieldOutputs["TEMP"].getSubset(region=region).values
            if any(v.data and v.data >= tcrit for v in vals):
                print(f"🔥 Delamination of {delete_set} at t={fr.frameValue:.3f} min")
                return fr.frameValue, fr.incrementNumber
        fr = step.frames[-1]
        print(f"⚠ No node ≥{tcrit}°C; using last frame {fr.frameValue:.3f}")
        return fr.frameValue, fr.incrementNumber
    finally:
        odb.close()



def main():
    print("=== CLT Delamination Control ===")
    base_inp = input("📁 Basic input file (without .inp extension): ").strip()
    if not base_inp.lower().endswith(".inp"):
        base_inp += ".inp"
    layers_json = input("📄 Layers for delamination (e.g., layers.json): ").strip()
    base_amp = input("🔥 Fire temperature amplitude (e.g., ISO): ").strip() or "ISO"
    cpus_in = input("🧠 Number of CPUs to use (default=8): ").strip()
    cpus = int(cpus_in) if cpus_in else 8

    abaqus, job_prefix, start_index, extend = "abaqus", "Delamination", 2, 30
    layers = json.load(open(layers_json))
    if not isinstance(layers, list) or not layers:
        raise RuntimeError("layers_json must be a non-empty list")

    base_job = os.path.splitext(os.path.basename(base_inp))[0]
    base_odb = f"{base_job}.odb"


    if not os.path.exists(base_odb):
        print(f"⚙ Running base input: {base_inp}")
        run_and_wait(abaqus, base_job, base_inp, "", cpus)
    else:
        print(f"✔ Base ODB found: {base_odb}")

    prev_inp, prev_amp, prev_job = base_inp, base_amp, base_job
    jobs = [base_job]


    for i,L in enumerate(layers, 1):
        odb_path = f"{prev_job}.odb"
        tf, inc = first_hit(odb_path, f"Step-{i}", L["watch"], L["delete"], L.get("tcrit", 300))
        data = read_amp(prev_inp, prev_amp)
        curve,Ttf = rebase(data, tf, extend)
        new_amp, inp = f"{prev_amp}_CONT", f"restart_L{i}.inp"
        write_restart(inp, tf, i, inc, new_amp, curve, f"Step-{i+1}", L.get("dur",15), L["delete"], L["surface"])
        job = f"{job_prefix}{start_index+i-1}"
        run_and_wait(abaqus, job, inp, prev_job, cpus)
        prev_inp, prev_amp, prev_job = inp, new_amp, job
        jobs.append(job)


    print("\n=== Auto merging ===")
    base = jobs[0]
    for rest in jobs[1:]:
        cmd = f'{abaqus} restartjoin originalodb={base} restartodb={rest} copyoriginal'
        print(">>", cmd)
        subprocess.run(cmd, shell=True, check=True)
        base = f"Restart_{base}"
    final = f"{jobs[0]}_ALL.odb"
    shutil.copyfile(f"{base}.odb", final)
    print(f"✔ Merged ODB: {final}")

if __name__ == "__main__":
    main()
