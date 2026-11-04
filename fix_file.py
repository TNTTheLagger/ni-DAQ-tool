with open('ni_usb6363_monitor.py', 'r') as f:
    content = f.read()

# Find and fix the broken line
old = '                "nidaqmx is not installed. Install with:\\n"\n                "pip install nidaqmx matplotlib numpy")\n'

if old in content:
    content = content.replace(old, '                "nidaqmx is not installed. Install with:\\n"\n                "pip install nidaqmx matplotlib numpy")\n')
    print("Fixed!")
else:
    # Try to find what's actually there around line 714
    lines = content.split('\n')
    for i in range(710, 720):
        print(f'{i+1}: {repr(lines[i])}')
