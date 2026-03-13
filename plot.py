import matplotlib.pyplot as plt
import numpy as np

# Data
real = np.array([1, 2.4, 2.4, 6.8, 12, 15, 18, 22, 27, 36, 270, 360, 360, 3300, 6200, 10000])
measured = np.array([1, 2.7, 3.1, 7.5, 12.9, 16.6, 19.9, 23.8, 29.2, 38.5, 237.8, 306, 305, 2597, 4896, 8135])

# Keep only values < 500 Ω
mask = real < 500
real = real[mask]
measured = measured[mask]

# Remove duplicate real resistance values (keep first)
unique_real, indices = np.unique(real, return_index=True)
real = real[indices]
measured = measured[indices]

# Sort for cleaner line plotting
order = np.argsort(real)
real = real[order]
measured = measured[order]

# Percent error
error = (measured - real) / real * 100

plt.figure(figsize=(10,6))

# Plot line + points
plt.plot(real, error, marker='o')

# Label offsets to avoid overlap
offsets = [(5,5), (5,-10), (5,10), (5,-15), (5,8), (5,-8), (5,12), (5,-12),
           (5,10), (5,-10), (5,10), (5,-10)]

for i, (x, y) in enumerate(zip(real, error)):
    dx, dy = offsets[i % len(offsets)]
    plt.annotate(f"{x}Ω",
                 (x, y),
                 textcoords="offset points",
                 xytext=(dx, dy),
                 fontsize=9)

plt.xlabel("Real Resistance (Ω)")
plt.ylabel("Percent Error (%)")
plt.title("Resistance Measurement Error (< 500Ω)")
plt.grid(True)

plt.show()