# 📊 phase_breakdown.py
import matplotlib.pyplot as plt
import numpy as np

# 📥 Raw data (seconds)
phases = ['Phase 1\n(Vision + Tables)', 'Phase 2\n(IOS Config Gen)']
load    = [10.06,    14.81]
prompt  = [611.4,    2816.1]
output  = [4896.4,  10314.5]

# 🎨 Setup
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6),
                                gridspec_kw={'width_ratios': [2, 1]})

# === Plot 1: Stacked bars (absolute time) ===
x = np.arange(len(phases))
width = 0.55

p1 = ax1.bar(x, load,   width, label='📥 Model load',  color='#4CAF50')
p2 = ax1.bar(x, prompt, width, bottom=load,
             label='🧠 Prompt eval (input)', color='#2196F3')
p3 = ax1.bar(x, output, width, bottom=np.array(load)+np.array(prompt),
             label='✍️ Output generation',   color='#FF9800')

# 🏷️ Labels on bars
totals = np.array(load) + np.array(prompt) + np.array(output)
for i, total in enumerate(totals):
    h = total/60
    ax1.text(i, total + 200, f'{h:.0f} min\n({total:.0f} s)',
             ha='center', fontweight='bold', fontsize=11)

ax1.set_ylabel('Time (seconds)', fontsize=12)
ax1.set_title('⏱️ Time breakdown per phase\nQwen3.6-35B-A3B on i7-1355U (CPU only)',
              fontsize=13, fontweight='bold')
ax1.set_xticks(x)
ax1.set_xticklabels(phases, fontsize=11)
ax1.legend(loc='upper left', fontsize=10)
ax1.grid(axis='y', alpha=0.3)
ax1.set_ylim(0, max(totals)*1.18)

# === Plot 2: Token rates comparison ===
metrics  = ['Prompt eval\nrate', 'Output gen\nrate']
phase1_r = [2.68, 3.80]
phase2_r = [7.05, 1.90]

x2 = np.arange(len(metrics))
width2 = 0.36
ax2.bar(x2 - width2/2, phase1_r, width2,
        label='Phase 1', color='#9C27B0')
ax2.bar(x2 + width2/2, phase2_r, width2,
        label='Phase 2', color='#E91E63')

for i, (v1, v2) in enumerate(zip(phase1_r, phase2_r)):
    ax2.text(i - width2/2, v1 + 0.15, f'{v1}', ha='center', fontweight='bold')
    ax2.text(i + width2/2, v2 + 0.15, f'{v2}', ha='center', fontweight='bold')

ax2.set_ylabel('Tokens / second', fontsize=12)
ax2.set_title('🐢 Throughput comparison',  fontsize=13, fontweight='bold')
ax2.set_xticks(x2)
ax2.set_xticklabels(metrics, fontsize=11)
ax2.legend(fontsize=10)
ax2.grid(axis='y', alpha=0.3)
ax2.set_ylim(0, 8.5)

plt.tight_layout()
plt.savefig('images/phase_breakdown.png', dpi=140, bbox_inches='tight')
plt.show()
print('✅ Saved to images/phase_breakdown.png')
