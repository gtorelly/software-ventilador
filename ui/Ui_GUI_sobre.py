# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/home/pi/front-end-unificado/front-end-unificado-20200909-ver0.1/ui/GUI_sobre.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Sobre(object):
    def setupUi(self, Sobre):
        Sobre.setObjectName("Sobre")
        Sobre.resize(800, 600)
        self.centralWidget = QtWidgets.QWidget(Sobre)
        self.centralWidget.setObjectName("centralWidget")
        self.label = QtWidgets.QLabel(self.centralWidget)
        self.label.setGeometry(QtCore.QRect(110, 30, 451, 181))
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setObjectName("label")
        Sobre.setCentralWidget(self.centralWidget)

        self.retranslateUi(Sobre)
        QtCore.QMetaObject.connectSlotsByName(Sobre)

    def retranslateUi(self, Sobre):
        _translate = QtCore.QCoreApplication.translate
        Sobre.setWindowTitle(_translate("Sobre", "MainWindow"))
        self.label.setText(_translate("Sobre", "Programa desenvolvido por Guilherme Torelly"))


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    Sobre = QtWidgets.QMainWindow()
    ui = Ui_Sobre()
    ui.setupUi(Sobre)
    Sobre.show()
    sys.exit(app.exec_())

