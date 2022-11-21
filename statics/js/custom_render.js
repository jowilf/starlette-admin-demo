Object.assign(render, {
  tags: function render(data, type, full, meta, fieldOptions) {
    if (data == null) return null_column();
    if (data.length == 0) return empty_column();
    data = data.map((d) => escape(d)); // Always escape database values
    if (type != "display") return data.join(","); // print, csv, pdf
    return `<div class="d-flex flex-row">${data
      .map(
        (tag) =>
          `<span class="me-1 badge bg-purple-lt"><i class="fa fa-tag"></i> ${tag}</span>`
      )
      .join("")}</div>`;
  },
});
