;
jQuery( function() {
    $("body").on('click','[data-stopPropagation]',function (e) {
        e.stopPropagation();
    });
    
    // 侧边栏
    $(document).on('click', '.pixels-aside-toggler', function() {
        $('.pixels-layout-sidebar').toggleClass('pixels-aside-open');
        $("body").toggleClass('pixels-layout-sidebar-close');
        
        if ($('.pixels-mask-modal').length == 0) {
            $('<div class="pixels-mask-modal"></div>').prependTo('body');
        } else {
            $( '.pixels-mask-modal' ).remove();
        }
    });
  
    // 遮罩层
    $(document).on('click', '.pixels-mask-modal', function() {
        $( this ).remove();
    	$('.pixels-layout-sidebar').toggleClass('pixels-aside-open');
        $('body').toggleClass('pixels-layout-sidebar-close');
    });
    
	// 侧边栏导航
    $(document).on('click', '.nav-item-has-subnav > a', function() {
		$subnavToggle = jQuery( this );
		$navHasSubnav = $subnavToggle.parent();
        $topHasSubNav = $subnavToggle.parents('.nav-item-has-subnav').last();
		$subnav       = $navHasSubnav.find('.nav-subnav').first();
        $viSubHeight  = $navHasSubnav.siblings().find('.nav-subnav:visible').outerHeight();
        $scrollBox    = $('.pixels-layout-sidebar-scroll');
		$navHasSubnav.siblings().find('.nav-subnav:visible').slideUp(500).parent().removeClass('open');
		$subnav.slideToggle( 300, function() {
			$navHasSubnav.toggleClass( 'open' );
			
			// 新增滚动条处理
			var scrollHeight  = 0;
			    pervTotal     = $topHasSubNav.prevAll().length,
			    boxHeight     = $scrollBox.outerHeight(),
		        innerHeight   = $('.sidebar-main').outerHeight(),
                thisScroll    = $scrollBox.scrollTop(),
                thisSubHeight = $(this).outerHeight(),
                footHeight    = 121;
			
			if (footHeight + innerHeight - boxHeight >= (pervTotal * 48)) {
			    scrollHeight = pervTotal * 48;
			}
            if ($subnavToggle.parents('.nav-item-has-subnav').length == 1) {
                $scrollBox.animate({scrollTop: scrollHeight}, 300);
            } else {
                // 子菜单操作
                if (typeof($viSubHeight) != 'undefined' && $viSubHeight != null) {
                    scrollHeight = thisScroll + thisSubHeight - $viSubHeight;
                    $scrollBox.animate({scrollTop: scrollHeight}, 300);
                } else {
                    if ((thisScroll + boxHeight - $scrollBox[0].scrollHeight) == 0) {
                        scrollHeight = thisScroll - thisSubHeight;
                        $scrollBox.animate({scrollTop: scrollHeight}, 300);
                    }
                }
            }
		});
	});
});

function getSchemas() {
    $.ajax({
        type: 'POST',
        url: 'http://10.78.50.215:8081/api/metadata/get-schemas',
        contentType: 'application/json',
        data: JSON.stringify({}),
        success: function (response) {
            var schemaMenu = $('#schemaMenu');

            // Clear existing items
            schemaMenu.empty();

            if (Array.isArray(response.schemas) && response.schemas.length > 0) {
                response.schemas.forEach(function (schema) {
                    var listItem = $('<li class="nav-item nav-item-has-subnav"><a href="#" onclick="showTables(\'' + schema.name + '\')">' + schema.name + '</a><ul class="nav nav-subnav" id="' + schema.name + '"></ul></li>');
                    schemaMenu.append(listItem);
                });
            } else {
                // If no schemas, show an "empty" first-level menu
                var emptySchemaItem = $('<li><a href="#">empty</a></li>');
                schemaMenu.append(emptySchemaItem);
            }
        },
        error: function (error) {
            console.error('Error fetching schemas:', error);
        }
    });
}

// Define getTables function
showTables = function getTables(schema) {
    $.ajax({
        type: 'POST',
        url: 'http://10.77.110.36:8081/api/metadata/get-tables',
        contentType: 'application/json',
        data: JSON.stringify({ "schemaName": schema }),
        success: function(response) {
            var tableMenu = $('#' + schema); // Use a unique ID for each schema's table menu

            // Clear existing items
            tableMenu.empty();
            console.log(response);
            if (Array.isArray(response.tables) && response.tables.length > 0) {
                response.tables.forEach(function(table) {
                    var listItem = $('<li class="nav-item nav-item-has-subnav"><a href="javascript:void(0)" onclick="showColumns(\'' + schema + '\', \'' + table.name + '\')">' + table.name + '</a><ul class="nav nav-subnav" id="' + schema + '_' + table.name + '"></ul></li>');
                    tableMenu.append(listItem);
                });
            } else {
                // If no tables, show an "empty" second-level menu
                var emptyTableItem = $('<li><a href="#">empty</a></li>');
                tableMenu.append(emptyTableItem);
            }
        },
        error: function(error) {
            console.error('Error fetching tables:', error);
        }
    });
}

// 添加一个函数，用于在聊天区域显示用户输入的消息和执行结果
function sendQuery() {
    var chatInput = document.getElementById('chat-input').value;
    var executionHintSelect = document.getElementById('execution-hint-select').value;
    var outputRowsInput = document.getElementById('output-rows-input').value;
    var chatArea = document.getElementById('chat-area');

    // 创建一个新的消息元素，代表用户输入的消息
    var userMessageElement = document.createElement('div');
    userMessageElement.className = 'user-message';
    userMessageElement.textContent = 'User: ' + chatInput;

    // 将新的消息元素添加到聊天区域
    chatArea.appendChild(userMessageElement);

    // 发送后端请求，执行查询
    executeQuery(chatInput, executionHintSelect, outputRowsInput, chatArea);
}

// 发送后端请求，执行查询
function executeQuery(query, executionHint, outputRows, chatArea) {
    // 构建SubmitQueryRequest对象
    var submitQueryRequest = {
        query: query,
        executionHint: executionHint,
        limitRows: outputRows || 10,
    };

    // 发起submitQuery请求
    fetch('http://10.77.110.36:8081/api/query/submit-query', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(submitQueryRequest),
    })
        .then(response => response.json())
        .then(data => {
            // 处理返回的数据，更新聊天区域
            console.log('Query Response:', data);

            // 恢复 query 默认值
            document.getElementById('chat-input').value = ""

            // 创建结果显示区域
            var resultDisplay = document.createElement('div');
            resultDisplay.className = 'query-result';
            resultDisplay.textContent = 'Query Status: ' + data.traceToken + '\n'
                + 'Results: (To be filled once the query completes)';

            // 将新的结果显示区域添加到聊天区域
            chatArea.appendChild(resultDisplay);

            // 如果查询成功，继续处理
            if (data.errorCode === 0) {
                // 显示查询状态
                showQueryStatus(data.traceToken, resultDisplay);
            } else {
                // 如果查询失败，显示错误消息
                resultDisplay.textContent = 'Error: ' + data.errorMessage;
            }
        })
        .catch(error => {
            console.error('Error:', error);
            // 在出错时更新结果显示区域
            resultDisplay.textContent = 'Error occurred during query execution.';
        });
}

// 显示查询状态
function showQueryStatus(traceToken, resultDisplay) {
    // 定义标志，判断是否继续刷新状态
    var shouldRefresh = true;

    // 定时刷新查询状态
    var refreshInterval = setInterval(function () {
        if (shouldRefresh) {
            refreshQueryStatus(traceToken, function (status) {
                // 如果查询状态为 "finished"，停止刷新
                if (status.toLowerCase() === 'finished') {
                    shouldRefresh = false;
                    clearInterval(refreshInterval);

                    // 轮询后端以获取查询结果
                    pollForResult(traceToken, resultDisplay);
                }
            });
        }
    }, 500); // 每5秒刷新一次，根据需求调整
}

// 刷新查询状态
function refreshQueryStatus(traceToken, callback) {
    // 构造GetQueryStatusRequest
    var getRequest = {
        traceTokens: [traceToken]
    };

    // 发送请求到后端
    fetch('http://10.77.110.36:8081/api/query/get-query-status', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(getRequest),
    })
        .then(response => response.json())
        .then(data => {
            console.log(data);

            // 处理后端返回的查询状态
            if (data.errorCode === 0) {
                var status = data.queryStatuses[traceToken];

                // 执行回调函数，传递查询状态
                if (typeof callback === 'function') {
                    callback(status);
                }
            } else {
                console.error('Error getting query status:', data.errorMessage);
            }
        })
        .catch(error => {
            console.error('Error refreshing query status:', error);
        });
}

// 轮询后端以获取查询结果
function pollForResult(traceToken, resultDisplay) {
    // 定义轮询间隔（ms）
    const pollInterval = 1000;

    // 开始轮询
    const pollTimer = setInterval(function () {
        // 发起getQueryResult请求
        fetch('http://10.77.110.36:8081/api/query/get-query-result', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ traceToken: traceToken }),
        })
            .then(response => response.json())
            .then(result => {
                console.log(result);

                // 如果查询完成，停止轮询并显示结果
                if (result.errorCode === 0) {
                    clearInterval(pollTimer);

                    // 显示查询结果
                    displayQueryResult(result, resultDisplay);
                } else if (result.errorCode !== 10405) {
                    // 如果发生错误，停止轮询并显示错误消息
                    clearInterval(pollTimer);
                    resultDisplay.textContent = 'Error: ' + result.errorMessage;
                }
                // 如果还未完成，继续轮询
            })
            .catch(error => {
                console.error('Error:', error);
                // 如果出现错误，停止轮询并显示错误消息
                clearInterval(pollTimer);
                resultDisplay.textContent = 'Error occurred while getting query result.';
            });
    }, pollInterval);
}

// 修改显示查询结果的函数，保留第一行的状态信息
function displayQueryResult(result, resultDisplay) {
    // 获取显示结果的DOM元素
    var resultDisplayContent = document.createElement('div');

    // 处理成功的情况
    var columnNames = result.columnNames;
    var rows = result.rows;
    var columnPrintSizes = result.columnPrintSizes;

    // 输出列名
    var columnNamesStr = '';
    columnNames.forEach(function (columnName, index) {
        var columnPrintSize = columnPrintSizes[index] || columnName.length + 2;
        columnNamesStr += padRight(columnName, columnPrintSize);
    });
    resultDisplayContent.textContent += columnNamesStr + '\n';

    // 输出行数据
    rows.forEach(function (row) {
        var rowStr = '';
        columnNames.forEach(function (columnName, index) {
            var columnPrintSize = columnPrintSizes[index];
            var value = row[index];
            if (value === undefined || value === null) {
                value = 'null';
            }
            rowStr += padRight(value, columnPrintSize);
        });
        resultDisplayContent.textContent += rowStr + '\n';
    });

    // 将新的结果显示区域添加到已有的结果显示区域
    resultDisplay.appendChild(resultDisplayContent);
}

// 辅助函数：右对齐并填充空格
function padRight(str, length) {
    return (str + ' '.repeat(Math.max(0, length - str.length))).substring(0, length);
}