from core.controller.atlas_controller import AtlasController


print("="*50)
print("ATLAS CONTROLLER TEST")
print("="*50)


controller = AtlasController()


print(controller.status())


print(controller.start())


print(controller.status())


print(controller.stop())


print(controller.status())