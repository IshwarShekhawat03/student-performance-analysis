import pandas as pd
import matplotlib.pyplot as plt

data = {
    "Name": ["A", "B", "C", "D", "E"],
    "Math": [85, 78, 92, 70, 88],
    "Science": [90, 75, 85, 60, 95]
}

df = pd.DataFrame(data)

df["Average"] = (df["Math"] + df["Science"]) / 2

print(df)

df.plot(x="Name", y=["Math", "Science"], kind="bar")
plt.title("Student Performance")
plt.show()
