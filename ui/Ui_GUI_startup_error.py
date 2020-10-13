# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/home/pi/software-ventilador/ui/GUI_startup_error.ui'
#
# Created by: PyQt5 UI code generator 5.11.3
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_StartupError(object):
    def setupUi(self, StartupError):
        StartupError.setObjectName("StartupError")
        StartupError.resize(377, 300)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(StartupError.sizePolicy().hasHeightForWidth())
        StartupError.setSizePolicy(sizePolicy)
        font = QtGui.QFont()
        font.setFamily("Arial Black")
        font.setPointSize(18)
        font.setBold(False)
        font.setItalic(False)
        font.setWeight(9)
        StartupError.setFont(font)
        StartupError.setStyleSheet("*{color:rgb(255,255,255);background-color:rgb(180, 0, 0);font: 75 18pt \"Arial Black\";}\n"
"QPushButton{background-color:rgb(0, 150, 0); border:3px solid rgb(0, 255, 0)}")
        self.centralWidget = QtWidgets.QWidget(StartupError)
        self.centralWidget.setAutoFillBackground(False)
        self.centralWidget.setObjectName("centralWidget")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.centralWidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QtWidgets.QLabel(self.centralWidget)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.startup_error_btn = QtWidgets.QPushButton(self.centralWidget)
        self.startup_error_btn.setAutoFillBackground(False)
        self.startup_error_btn.setStyleSheet("")
        self.startup_error_btn.setObjectName("startup_error_btn")
        self.verticalLayout.addWidget(self.startup_error_btn)
        StartupError.setCentralWidget(self.centralWidget)

        self.retranslateUi(StartupError)
        QtCore.QMetaObject.connectSlotsByName(StartupError)

    def retranslateUi(self, StartupError):
        _translate = QtCore.QCoreApplication.translate
        StartupError.setWindowTitle(_translate("StartupError", "Startup Error!"))
        self.label.setText(_translate("StartupError", "FALHA DE INICIALIZAÇÃO!\n"
"Verifique o ar comprimido e se há obstruções ao movimento do pistão.\n"
"Aperte INICIAR para tentar novamente."))
        self.startup_error_btn.setText(_translate("StartupError", "INICIAR"))

