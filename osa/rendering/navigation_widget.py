import vtk


class NavigationWidget:
    @staticmethod
    def create(plotter):
        widget = vtk.vtkCameraOrientationWidget()
        widget.SetParentRenderer(plotter.renderer)
        widget.SetInteractor(plotter.iren.interactor)
        widget.GetRepresentation().AnchorToLowerLeft()
        widget.SetEnabled(1)
        return widget
