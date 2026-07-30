import os
import py_compile

print("\nATLAS AI CODE CHECK\n")

errors = []

for root, dirs, files in os.walk("."):

    for file in files:

        if file.endswith(".py"):

            path = os.path.join(root, file)

            try:
                py_compile.compile(
                    path,
                    doraise=True
                )

                print(f"[OK] {path}")

            except Exception as e:

                print(f"[ERROR] {path}")

                errors.append(
                    (path, str(e))
                )


print("\n====================")

if errors:

    print("HATALAR BULUNDU:\n")

    for e in errors:
        print(e[0])
        print(e[1])

else:

    print("Tum Python dosyalari temiz.")


print("====================")