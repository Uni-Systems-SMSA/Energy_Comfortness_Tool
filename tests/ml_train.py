from ece.pipeline import main_train_all_targets
reports = main_train_all_targets()
print("Training completed. Reports written:")
for target, path in reports.items():
    print(f"{target}: {path}")
