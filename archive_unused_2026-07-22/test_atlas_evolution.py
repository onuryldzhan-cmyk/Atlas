"""
Atlas Evolution Test v6.6
"""

from core.atlas_brain import AtlasBrain



brain = AtlasBrain()



print("\n==============================")
print(" ATLAS EVOLUTION TEST ")
print("==============================")



result = brain.check_improvements()



print("\n===== ANALYSIS =====")

print(
    result.get(
        "analysis"
    )
)



print("\n===== UPGRADE RESULTS =====")


for item in result.get(
    "upgrade_results",
    []
):

    print(item)