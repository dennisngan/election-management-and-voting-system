pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var stock
    required property var words
    property string locale: "tc"
    readonly property var editorState: stock.state
    readonly property var form: editorState.forms
    readonly property var context: editorState.context || ({})
    readonly property var election: context.election || ({})
    readonly property var constituency: context.constituency || ({})
    readonly property var station: context.station || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property bool hasSelected: !!selected.id
    readonly property bool canEdit: editorState.role === "polling_officer"
        && (election.status === "draft" || election.status === "active")
        && !editorState.historical
    readonly property var pools: ["ordinary", "replacement", "tendered"]
    property string pendingAction: "receipt"
    property int pendingId: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function selectedIndex() {
        for (var i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].id === selected.id) return i
        return -1
    }
    function receiptLabel(row) {
        return page.t("stock_receipt") + " " + row.id + " · " + row.series + " · "
            + page.t("revision") + " " + row.revision + " · " + row.total_display
    }
    function chooseReceipt(receiptId) {
        if (editorState.busy) return
        if (!stock.loadReceipt(receiptId, false)) {
            pendingAction = "receipt"
            pendingId = receiptId
            discardDialog.open()
        }
    }
    function chooseRevision(revision) {
        if (editorState.busy) return
        if (!stock.loadRevision(revision, false)) {
            pendingAction = "revision"
            pendingId = revision
            discardDialog.open()
        }
    }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function exportReport(format) {
        if (!hasSelected || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/stock-receipt-"
            + selected.id + "-r" + selected.revision + "-" + locale + "." + format
        exportDialog.open()
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            text: page.t("received_stock")
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 28
            font.weight: Font.Medium
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            onClicked: page.stock.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormNotice {
        words: page.words
        autoReveal: false
        notice: page.editorState.newer_revision ? "stock_newer_revision" : ""
        onReveal: control => page.reveal(control)
    }

    FormPanel {
        implicitHeight: contextLayout.implicitHeight + 40
        ColumnLayout {
            id: contextLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 8
            FormCaption {
                text: page.editorState.station_id ? page.election.name || "" : page.t("select_station")
                color: "#25344b"
                font.pixelSize: 18
            }
            FormCaption {
                visible: !!page.editorState.station_id
                text: (page.constituency.code || "") + " · " + (page.constituency.name || "")
                    + "\n" + (page.station.code || "") + " · " + (page.station.name || "")
            }
            FormCaption {
                visible: !!page.editorState.station_id
                text: page.t("role") + " · " + page.t(page.editorState.role || "") + "   "
                    + page.t("election_status") + " · " + page.t(page.election.status || "")
            }
            FormCaption {
                visible: !!page.editorState.station_id && !page.canEdit
                text: page.t(page.election.status === "finalized" ? "election_read_only" : "stock_read_only")
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: pickerLayout.implicitHeight + 40
        ColumnLayout {
            id: pickerLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                FormCaption { text: page.t("stock_receipts") }
                FormButton {
                    visible: page.editorState.role === "polling_officer"
                        && (page.election.status === "draft" || page.election.status === "active")
                    text: page.t("new_stock_receipt")
                    flat: true
                    highlighted: false
                    working: page.editorState.busy
                    onClicked: page.chooseReceipt(0)
                    onReveal: control => page.reveal(control)
                }
            }
            ComboBox {
                id: receiptPicker
                objectName: "stockReceiptPicker"
                visible: page.editorState.items.length > 0
                Layout.fillWidth: true
                enabled: !page.editorState.busy
                model: page.editorState.items
                currentIndex: page.selectedIndex()
                displayText: page.hasSelected ? page.receiptLabel(page.selected) : page.t("select_stock_receipt")
                Accessible.name: page.t("select_stock_receipt")
                contentItem: Text {
                    text: receiptPicker.displayText
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font: receiptPicker.font
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: receiptDelegate
                    required property var modelData
                    required property int index
                    width: receiptPicker.width
                    text: page.receiptLabel(modelData)
                    highlighted: receiptPicker.highlightedIndex === index
                    contentItem: Text {
                        text: receiptDelegate.text
                        textFormat: Text.PlainText
                        color: "#25344b"
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: {
                    page.chooseReceipt(model[currentIndex].id)
                    currentIndex = Qt.binding(function() { return page.selectedIndex() })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (receiptPicker.activeFocus) page.reveal(receiptPicker) })
            }
            FormCaption {
                visible: page.editorState.items.length === 0
                text: page.t(page.editorState.refreshing ? "loading" : "no_stock_receipts")
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id && (page.canEdit || page.hasSelected)
        implicitHeight: receiptForm.implicitHeight + 40
        ColumnLayout {
            id: receiptForm
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                FormCaption {
                    text: page.hasSelected
                        ? page.t(page.editorState.historical ? "stock_historical" : "stock_current")
                            + " · " + page.t("revision") + " " + page.selected.revision
                            + (page.editorState.dirty ? " •" : "")
                        : page.t("editing_new")
                }
                FormButton {
                    visible: page.hasSelected
                    text: page.t(page.editorState.historical ? "stock_return_current" : "reload_saved")
                    flat: true
                    highlighted: false
                    working: page.editorState.busy
                    onClicked: page.chooseReceipt(page.selected.id)
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption {
                visible: page.hasSelected
                text: page.t("stock_recorded") + " · " + page.t("stock_total_received")
                    + " " + (page.selected.total_display || "—")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 2 : 1
                columnSpacing: 20
                rowSpacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("stock_series") }
                    FormField {
                        objectName: "stockSeries"
                        text: page.form.series
                        maximumLength: 64
                        working: page.editorState.busy
                        readOnly: !page.canEdit
                        Accessible.name: page.t("stock_series")
                        onTextEdited: page.stock.setField("series", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("stock_event_at") }
                    FormField {
                        objectName: "stockEventAt"
                        text: page.form.event_at
                        placeholderText: "YYYY-MM-DD HH:mm"
                        working: page.editorState.busy
                        readOnly: !page.canEdit
                        Accessible.name: page.t("stock_event_at")
                        onTextEdited: page.stock.setField("event_at", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption { text: page.t("stock_time_hint") }
            FormCaption { text: page.t("stock_pool_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 20
                rowSpacing: 12
                Repeater {
                    model: page.pools
                    delegate: ColumnLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        FormCaption { text: page.t("stock_pool_" + parent.modelData) }
                        FormField {
                            objectName: "stockQuantity_" + parent.modelData
                            text: page.form[parent.modelData + "_quantity"]
                            maximumLength: 19
                            inputMethodHints: Qt.ImhDigitsOnly
                            working: page.editorState.busy
                            readOnly: !page.canEdit
                            Accessible.name: page.t("stock_pool_" + parent.modelData)
                            onTextEdited: page.stock.setField(parent.modelData + "_quantity", text)
                            onReveal: control => page.reveal(control)
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                FormCaption {
                    text: page.t("stock_calculated_total") + "  "
                        + (page.editorState.calculated_total_display || "—")
                    font.pixelSize: 16
                    color: "#25344b"
                }
                FormButton {
                    visible: page.canEdit
                    objectName: "stockAddRange"
                    text: page.t("stock_add_range")
                    flat: true
                    highlighted: false
                    working: page.editorState.busy
                    onClicked: page.stock.addRange()
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption { text: page.t("stock_serial_hint") }
            FormCaption {
                visible: page.editorState.ranges.length === 0
                text: page.t("no_stock_ranges")
            }
            Repeater {
                // A numeric model keeps delegates alive while Python replaces edited row values.
                model: page.editorState.ranges.length
                delegate: FormPanel {
                    id: rangeRow
                    required property int index
                    readonly property var row: page.editorState.ranges[index] || ({})
                    color: "#f7f9fd"
                    radius: 12
                    implicitHeight: rangeLayout.implicitHeight + 28
                    ColumnLayout {
                        id: rangeLayout
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            FormCaption { text: page.t("stock_range") + " " + (rangeRow.index + 1) }
                            FormButton {
                                visible: page.canEdit
                                objectName: "stockRemoveRange" + rangeRow.index
                                text: page.t("stock_remove_range")
                                Accessible.name: text + " " + (rangeRow.index + 1)
                                flat: true
                                highlighted: false
                                working: page.editorState.busy
                                onClicked: page.stock.removeRange(rangeRow.index)
                                onReveal: control => page.reveal(control)
                            }
                        }
                        FormCaption { text: page.t("stock_pool") }
                        ComboBox {
                            id: poolPicker
                            objectName: "stockRangePool" + rangeRow.index
                            Layout.fillWidth: true
                            model: page.pools
                            enabled: page.canEdit && !page.editorState.busy
                            currentIndex: page.pools.indexOf(rangeRow.row.pool)
                            displayText: page.t("stock_pool_" + (rangeRow.row.pool || "ordinary"))
                            Accessible.name: page.t("stock_pool") + " " + (rangeRow.index + 1)
                            delegate: ItemDelegate {
                                required property string modelData
                                required property int index
                                width: poolPicker.width
                                text: page.t("stock_pool_" + modelData)
                                highlighted: poolPicker.highlightedIndex === index
                            }
                            onActivated: {
                                page.stock.setRange(rangeRow.index, "pool", model[currentIndex])
                                currentIndex = Qt.binding(function() {
                                    return page.pools.indexOf(rangeRow.row.pool)
                                })
                            }
                            onActiveFocusChanged: if (activeFocus)
                                Qt.callLater(function() { if (poolPicker.activeFocus) page.reveal(poolPicker) })
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: page.width > 900 ? 3 : 1
                            columnSpacing: 16
                            rowSpacing: 12
                            ColumnLayout {
                                Layout.fillWidth: true
                                FormCaption { text: page.t("stock_serial_from") }
                                FormField {
                                    objectName: "stockSerialFrom" + rangeRow.index
                                    text: rangeRow.row.serial_from || ""
                                    maximumLength: 18
                                    inputMethodHints: Qt.ImhDigitsOnly
                                    working: page.editorState.busy
                                    readOnly: !page.canEdit
                                    Accessible.name: page.t("stock_serial_from") + " " + (rangeRow.index + 1)
                                    onTextEdited: page.stock.setRange(rangeRow.index, "serial_from", text)
                                    onReveal: control => page.reveal(control)
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                FormCaption { text: page.t("stock_serial_to") }
                                FormField {
                                    objectName: "stockSerialTo" + rangeRow.index
                                    text: rangeRow.row.serial_to || ""
                                    maximumLength: 18
                                    inputMethodHints: Qt.ImhDigitsOnly
                                    working: page.editorState.busy
                                    readOnly: !page.canEdit
                                    Accessible.name: page.t("stock_serial_to") + " " + (rangeRow.index + 1)
                                    onTextEdited: page.stock.setRange(rangeRow.index, "serial_to", text)
                                    onReveal: control => page.reveal(control)
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                FormCaption { text: page.t("stock_range_quantity") }
                                FormField {
                                    objectName: "stockRangeQuantity" + rangeRow.index
                                    text: rangeRow.row.quantity_display || "—"
                                    working: page.editorState.busy
                                    readOnly: true
                                    Accessible.name: page.t("stock_range_quantity") + " " + (rangeRow.index + 1)
                                    onReveal: control => page.reveal(control)
                                }
                            }
                        }
                    }
                }
            }
            FormCaption {
                visible: page.hasSelected && page.canEdit
                text: page.t("stock_correction_hint")
            }
            FormCaption {
                visible: page.hasSelected
                text: page.t("stock_reason")
            }
            TextArea {
                id: correctionReason
                objectName: "stockCorrectionReason"
                visible: page.hasSelected
                Layout.fillWidth: true
                implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
                text: page.canEdit ? page.form.reason : page.selected.reason || ""
                textFormat: TextEdit.PlainText
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(correctionReason, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(correctionReason, false); event.accepted = true }
                clip: true
                wrapMode: TextEdit.WordWrap
                selectByMouse: true
                enabled: !page.editorState.busy
                readOnly: !page.canEdit
                padding: 12
                Accessible.name: page.t("stock_reason")
                onTextEdited: page.stock.setField("reason", text)
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (correctionReason.activeFocus) page.reveal(correctionReason) })
                background: Rectangle {
                    radius: 8
                    color: "white"
                    border.color: correctionReason.activeFocus ? "#1967d2" : "#a7b2c2"
                    border.width: correctionReason.activeFocus ? 2 : 1
                }
            }
            FormButton {
                visible: page.canEdit
                objectName: "stockSave"
                text: page.t(page.editorState.busy ? "saving" : page.hasSelected ? "stock_save_correction" : "stock_save")
                Layout.fillWidth: true
                working: page.editorState.busy
                enabled: !working && (!page.hasSelected || page.editorState.dirty)
                onClicked: page.stock.save()
                onReveal: control => page.reveal(control)
            }
        }
    }

    FormPanel {
        visible: page.hasSelected
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Label {
                text: page.t("stock_history")
                textFormat: Text.PlainText
                color: "#25344b"
                font.pixelSize: 20
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            FormCaption {
                visible: page.editorState.history.length === 0
                text: page.t(page.editorState.refreshing ? "loading" : "no_stock_history")
            }
            Repeater {
                model: page.editorState.history
                delegate: FormButton {
                    id: historyButton
                    required property var modelData
                    objectName: "stockHistoryRevision" + modelData.revision
                    Layout.fillWidth: true
                    text: page.t("revision") + " " + modelData.revision + " · " + modelData.series
                        + " · " + page.stock.formatTime(modelData.event_at) + " · " + modelData.total_display
                    flat: true
                    highlighted: false
                    working: page.editorState.busy
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: historyButton.text
                        textFormat: Text.PlainText
                        color: "#1967d2"
                        font: historyButton.font
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: page.chooseRevision(modelData.revision)
                    onReveal: control => page.reveal(control)
                }
            }
        }
    }

    FormPanel {
        visible: page.hasSelected
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Label {
                text: page.t("stock_report")
                textFormat: Text.PlainText
                color: "#25344b"
                font.pixelSize: 20
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            FormCaption { text: page.t("stock_report_hint") }
            FormCaption {
                text: page.t("stock_report_language") + " · " + page.languageName(page.locale)
                    + "   " + page.t("revision") + " " + page.selected.revision
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 8
                FormButton {
                    objectName: "stockPreview"
                    text: page.t("stock_preview")
                    working: page.editorState.busy
                    Layout.fillWidth: true
                    onClicked: page.stock.preview(page.locale)
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "stockExportPdf"
                    text: page.t("stock_export_pdf")
                    working: page.editorState.busy
                    Layout.fillWidth: true
                    flat: true
                    highlighted: false
                    onClicked: page.exportReport("pdf")
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "stockExportCsv"
                    text: page.t("stock_export_csv")
                    working: page.editorState.busy
                    Layout.fillWidth: true
                    flat: true
                    highlighted: false
                    onClicked: page.exportReport("csv")
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · "
                    + page.languageName((page.editorState.report || ({})).locale || page.locale)
            }
            TextArea {
                id: reportText
                objectName: "stockReportPreview"
                visible: !!page.editorState.report_text
                Layout.fillWidth: true
                readOnly: true
                selectByMouse: true
                text: page.editorState.report_text || ""
                textFormat: TextEdit.PlainText
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(reportText, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(reportText, false); event.accepted = true }
                clip: true
                wrapMode: TextEdit.WrapAnywhere
                Accessible.name: page.t("stock_report")
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (reportText.activeFocus) page.reveal(reportText) })
            }
            FormCaption {
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "revision") page.stock.loadRevision(page.pendingId, true)
            else page.stock.loadReceipt(page.pendingId, true)
        }
    }
    FileDialog {
        id: exportDialog
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.stock.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
