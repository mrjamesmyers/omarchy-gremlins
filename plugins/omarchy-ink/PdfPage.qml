// Loaded opportunistically by Editor.qml. If QtQuick.Pdf is not present in
// this Qt build the Loader reports an error and the editor falls back to
// rendering the first page through Qt's PDF image plugin instead. Keeping the
// import in its own file is what makes that failure survivable - an import
// that fails inside Editor.qml would take the whole editor down with it.

import QtQuick
import QtQuick.Pdf

Item {
  id: root
  property string source: ""
  property int page: 0

  PdfDocument {
    id: document
    source: root.source
  }

  PdfPageImage {
    anchors.fill: parent
    document: document
    currentFrame: root.page
    fillMode: Image.PreserveAspectFit
    asynchronous: true
  }
}
